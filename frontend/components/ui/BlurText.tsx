import type { CSSProperties } from "react";

/** Words resolve from blur to sharp, one after another. */
export function BlurText({ text, offset = 0 }: { text: string; offset?: number }) {
  return (
    <>
      {text.split(" ").map((word, i) => (
        <span key={i}>
          <span className="blur-word" style={{ "--i": i + offset } as CSSProperties}>
            {word}
          </span>{" "}
        </span>
      ))}
    </>
  );
}
