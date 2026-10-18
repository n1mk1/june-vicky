/**
 * The currencies Vicky handles: CAD, the default reporting currency, plus every currency the Bank of
 * Canada publishes a daily rate for. Mirrors `backend/vicky/model/currencies.py`; conversion itself
 * happens in the backend, at Bank of Canada rates for each period.
 */

export const DEFAULT_CURRENCY = "cad";

/** code → [name, display prefix] */
export const CURRENCIES: Record<string, readonly [string, string]> = {
  cad: ["Canadian dollar", "$"],
  usd: ["US dollar", "US$"],
  eur: ["Euro", "€"],
  gbp: ["UK pound sterling", "£"],
  aud: ["Australian dollar", "A$"],
  nzd: ["New Zealand dollar", "NZ$"],
  jpy: ["Japanese yen", "¥"],
  cny: ["Chinese renminbi", "CN¥"],
  hkd: ["Hong Kong dollar", "HK$"],
  sgd: ["Singapore dollar", "S$"],
  twd: ["New Taiwan dollar", "NT$"],
  krw: ["South Korean won", "₩"],
  inr: ["Indian rupee", "₹"],
  idr: ["Indonesian rupiah", "Rp "],
  myr: ["Malaysian ringgit", "RM "],
  thb: ["Thai baht", "฿"],
  chf: ["Swiss franc", "CHF "],
  nok: ["Norwegian krone", "NOK "],
  sek: ["Swedish krona", "SEK "],
  pln: ["Polish zloty", "zł "],
  try: ["Turkish lira", "₺"],
  zar: ["South African rand", "R "],
  mxn: ["Mexican peso", "MX$"],
  brl: ["Brazilian real", "R$"],
  pen: ["Peruvian new sol", "S/ "],
};

export const CURRENCY_CODES = Object.keys(CURRENCIES);

export const isCurrency = (unit: string | null | undefined) => !!unit && unit.toLowerCase() in CURRENCIES;

export const currencySymbol = (code: string | null | undefined) =>
  CURRENCIES[(code ?? "").toLowerCase()]?.[1] ?? "$";

/** A known lowercase code, else CAD. */
export const normCurrency = (code: string | null | undefined) =>
  isCurrency(code) ? (code as string).toLowerCase() : DEFAULT_CURRENCY;
