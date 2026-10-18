/**
 * Browser half of the voice loop (docs/04-APP-FLOW.md §5). Speech in: the mic streams 16 kHz PCM to
 * ElevenLabs realtime Scribe with a single-use token from `POST /voice/stt-token` (the API key stays on the
 * server). Speech out: `GET /voice/tts` streams MP3 in the speaker's voice through the same-origin proxy.
 */

import { apiPost } from "./api";

interface SttToken {
  token: string;
  url: string;
  model_id: string;
  sample_rate: number;
}

/**
 * One microphone for a whole pitch. Audio goes to transcription only while it's resumed (it pauses while the
 * panel speaks, so their voices are never transcribed). The page reads `spoke()` and `silenceMs()` to decide
 * when a turn is over and calls `commit()` to take what was said.
 */
export interface Mic {
  /** Sends audio to transcription again (reconnecting with a fresh token if the socket closed). */
  resume: () => Promise<void>;
  /** Stops sending audio; what was heard stays until the next commit. */
  pause: () => void;
  /** Commits what was said since the last commit and resolves with its transcript ("" if nothing). */
  commit: () => Promise<string>;
  /** True once speech was heard since the last commit. */
  spoke: () => boolean;
  /** Milliseconds since speech was last heard (0 before any). */
  silenceMs: () => number;
  /** Input level, 0–1, smoothed (0 while paused). */
  level: () => number;
  close: () => void;
}

interface MicHandlers {
  /** What has been said since the last commit, as it comes in. */
  onPartial?: (text: string) => void;
  /** A transport or service failure; the page falls back to typing. */
  onError?: (message: string) => void;
}

const COMMIT_WAIT_MS = 4000;
const CHUNK_MS = 250;
// A frame counts as speech above max(MIN_SPEECH_RMS, noise floor × SPEECH_OVER_FLOOR); a turn needs
// SPEECH_MIN_MS of it, so a cough or a click doesn't count.
const MIN_SPEECH_RMS = 0.012;
const SPEECH_OVER_FLOOR = 2.6;
const SPEECH_MIN_MS = 220;

// Runs on the audio thread: forwards mono Float32 frames to the page.
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("vicky-tap", Tap);
`;

/** Box-filter resample to `to` Hz and convert to 16-bit PCM. */
function toPcm16(input: Float32Array, from: number, to: number): Int16Array {
  const ratio = from / to;
  const n = Math.floor(input.length / ratio);
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = a; j < b; j++) sum += input[j];
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, b - a)));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  return out;
}

function base64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

const tidy = (parts: string[]) => parts.join(" ").replace(/\s+/g, " ").trim();

export function micSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioWorkletNode !== "undefined";
}

/** Opens the mic (asking for permission). Starts paused; `resume()` opens transcription. */
export async function openMic({ onPartial, onError }: MicHandlers = {}): Promise<Mic> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  try {
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
  } catch (err) {
    stream.getTracks().forEach((t) => t.stop());
    void ctx.close().catch(() => {});
    throw err;
  }

  let cfg: SttToken | null = null;
  let ws: WebSocket | null = null;
  let connecting: Promise<void> | null = null;
  let active = false;
  let closed = false;
  let heard: string[] = [];
  let partial = "";
  let onCommit: (() => void) | null = null;
  let chain: Promise<unknown> = Promise.resolve();
  // Voice activity: a slow noise-floor estimate, how much speech since the last commit, and when it was heard.
  let floor = 0.004;
  let lvl = 0;
  let voicedMs = 0;
  let lastVoice = 0;

  const say = () => onPartial?.(tidy([...heard, partial]));

  const connect = (): Promise<void> => {
    if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve();
    if (connecting) return connecting;
    connecting = (async () => {
      const c = await apiPost<SttToken>("voice/stt-token");
      const qs = new URLSearchParams({
        model_id: c.model_id,
        token: c.token,
        audio_format: `pcm_${c.sample_rate}`,
        commit_strategy: "manual",
      });
      const sock = new WebSocket(`${c.url}?${qs}`);
      await new Promise<void>((resolve, reject) => {
        sock.onopen = () => resolve();
        sock.onerror = () => reject(new Error("Couldn't reach ElevenLabs transcription."));
      });
      sock.onmessage = (e) => {
        let msg: { message_type?: string; text?: string; error?: string };
        try {
          msg = JSON.parse(String(e.data));
        } catch {
          return;
        }
        if (msg.message_type === "partial_transcript") {
          partial = msg.text ?? "";
          say();
        } else if (msg.message_type === "committed_transcript") {
          if (msg.text?.trim()) heard.push(msg.text.trim());
          partial = "";
          say();
          onCommit?.();
        } else if (msg.error) {
          onError?.(`Transcription stopped: ${msg.error}`);
          onCommit?.();
        }
      };
      sock.onclose = () => {
        if (ws === sock) ws = null;
        onCommit?.();
      };
      cfg = c;
      ws = sock;
    })().finally(() => {
      connecting = null;
    });
    return connecting;
  };

  const send = (pcm: Int16Array, commit: boolean) => {
    if (!cfg || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: base64(pcm), commit, sample_rate: cfg.sample_rate }));
  };

  // Batch the worklet's 128-frame blocks into ~250 ms chunks.
  let buf = new Int16Array(0);
  const source = ctx.createMediaStreamSource(stream);
  const tap = new AudioWorkletNode(ctx, "vicky-tap");
  tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
    if (!active) return;
    const frame = e.data;
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    const rms = Math.sqrt(sum / Math.max(1, frame.length));
    lvl = lvl * 0.85 + Math.min(1, rms * 8) * 0.15;
    if (rms > Math.max(MIN_SPEECH_RMS, floor * SPEECH_OVER_FLOOR)) {
      voicedMs += (frame.length / ctx.sampleRate) * 1000;
      if (voicedMs >= SPEECH_MIN_MS) lastVoice = performance.now();
    } else {
      floor = floor * 0.995 + rms * 0.005;
    }
    // A socket closed by the service (a long pitch, a network blip) reopens on the next frame.
    if (!ws && !connecting && !closed) void connect().catch(() => onError?.("Transcription dropped and couldn't reconnect."));
    if (!cfg) return;
    const pcm = toPcm16(frame, ctx.sampleRate, cfg.sample_rate);
    const next = new Int16Array(buf.length + pcm.length);
    next.set(buf);
    next.set(pcm, buf.length);
    buf = next;
    if (buf.length >= Math.round((cfg.sample_rate * CHUNK_MS) / 1000)) {
      send(buf, false);
      buf = new Int16Array(0);
    }
  };
  source.connect(tap);

  const take = async (): Promise<string> => {
    voicedMs = 0;
    lastVoice = 0;
    if (cfg && ws && ws.readyState === WebSocket.OPEN) {
      // The tail plus 100 ms of silence, committed, so the last words come back as a final transcript.
      const tail = new Int16Array(buf.length + cfg.sample_rate / 10);
      tail.set(buf);
      buf = new Int16Array(0);
      await new Promise<void>((resolve) => {
        const timer = window.setTimeout(resolve, COMMIT_WAIT_MS);
        onCommit = () => {
          window.clearTimeout(timer);
          resolve();
        };
        send(tail, true);
      });
      onCommit = null;
    }
    const text = tidy([...heard, partial]);
    heard = [];
    partial = "";
    return text;
  };

  return {
    resume: async () => {
      if (closed) return;
      voicedMs = 0;
      lastVoice = 0;
      await connect();
      if (ctx.state === "suspended") await ctx.resume();
      active = true;
    },
    pause: () => {
      active = false;
      lvl = 0;
    },
    commit: () => {
      const next = chain.then(take, take);
      chain = next.catch(() => {});
      return next;
    },
    spoke: () => lastVoice > 0,
    silenceMs: () => (lastVoice > 0 ? performance.now() - lastVoice : 0),
    level: () => (active ? lvl : 0),
    close: () => {
      closed = true;
      active = false;
      tap.port.onmessage = null;
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => {});
      ws?.close();
      ws = null;
    },
  };
}

/**
 * Speaks `text` in `speaker`'s voice (a persona id, or "vicky"), or in `voiceId` when the sitting cast one;
 * resolves when playback ends or is cut.
 */
export function speak(text: string, speaker: string, signal?: AbortSignal, voiceId?: string): Promise<void> {
  const qs = new URLSearchParams({ text: text.slice(0, 1200), speaker });
  if (voiceId) qs.set("voice_id", voiceId);
  const audio = new Audio(`/api/v1/voice/tts?${qs}`);
  return new Promise<void>((resolve, reject) => {
    const done = () => {
      signal?.removeEventListener("abort", abort);
      resolve();
    };
    const abort = () => {
      audio.pause();
      audio.removeAttribute("src");
      done();
    };
    if (signal?.aborted) return done();
    signal?.addEventListener("abort", abort);
    audio.addEventListener("ended", done);
    audio.addEventListener("error", () => {
      signal?.removeEventListener("abort", abort);
      reject(new Error("The panel's voice didn't play."));
    });
    audio.play().catch((err: unknown) => {
      signal?.removeEventListener("abort", abort);
      reject(err instanceof Error ? err : new Error("The panel's voice didn't play."));
    });
  });
}
