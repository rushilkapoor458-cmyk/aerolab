/**
 * Spoken phraseology into command-line text.
 *
 * Browser speech recognition returns ordinary English prose: "air india one
 * zero one descend and maintain five thousand". The command parser wants
 * "AIC101 descend and maintain 5000". This module is the translation, and it
 * is deliberately pure — no DOM, no Web Speech API — so the mapping can be
 * tested without a microphone.
 *
 * The work is almost entirely in numbers. Controllers speak digits
 * individually ("two seven zero", not "two hundred and seventy") but speak
 * altitudes in whole thousands ("five thousand"), and recognisers render both
 * inconsistently: sometimes as words, sometimes already as digits, sometimes
 * as "270" when you said "two seven zero" and sometimes as "2 7 0".
 *
 * The order of the passes below matters. Airline names go first, because
 * "air india express" has to win over "air india". Digit words are folded
 * next, then the multi-word number forms that only make sense once the digits
 * are numerals, then runway suffixes last, because "two nine right" can only
 * be told from "turn right" once "runway" is known to be sitting in front
 * of it.
 */

/** Airline callsign prefixes, spoken form to ICAO designator. */
const AIRLINES: ReadonlyArray<readonly [RegExp, string]> = [
  // Longest first: "air india express" must not be eaten by "air india".
  [/\bair india express\b/g, 'AXB'],
  [/\bair india\b/g, 'AIC'],
  [/\bindigo\b/g, 'IGO'],
  [/\bvistara\b/g, 'VTI'],
  [/\bspice ?jet\b/g, 'SEJ'],
  [/\bemirates\b/g, 'UAE'],
  [/\bqatari\b/g, 'QTR'],
  [/\bqatar\b/g, 'QTR'],
];

/**
 * Digit words that are safe anywhere in a transmission, including the ICAO
 * pronunciations. Nothing here collides with a command word.
 */
const DIGITS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bzero\b/g, '0'],
  [/\boh\b/g, '0'],
  [/\bone\b/g, '1'],
  [/\btwo\b/g, '2'],
  [/\bthree\b/g, '3'],
  [/\btree\b/g, '3'],
  [/\bfour\b/g, '4'],
  [/\bfower\b/g, '4'],
  [/\bfive\b/g, '5'],
  [/\bfife\b/g, '5'],
  [/\bsix\b/g, '6'],
  [/\bseven\b/g, '7'],
  [/\beight\b/g, '8'],
  [/\bnine\b/g, '9'],
  [/\bniner\b/g, '9'],
];

/**
 * Homophones the recogniser reaches for when someone reads digits quickly:
 * "to" for two, "for" for four, "ate" for eight.
 *
 * These are only applied inside the callsign. In the body of a transmission
 * they are real words that phraseology depends on — "reduce speed **to** 210"
 * and "cleared **for** takeoff" would both be destroyed by folding them to
 * digits, so the substitution stops at the end of the callsign.
 */
const CALLSIGN_ONLY_DIGITS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bto\b/g, '2'],
  [/\btoo\b/g, '2'],
  [/\bfor\b/g, '4'],
  [/\bate\b/g, '8'],
];

/**
 * Words the recogniser inserts that carry no meaning for the parser. "And"
 * is kept, because "descend and maintain" is real phraseology.
 */
const NOISE = /\b(?:please|uh|um|er|okay|ok)\b/g;

/**
 * Spoken words the parser does not know, and words it needs kept.
 *
 * "Degrees" and "feet" are not parser tokens, so they go. "Knots" stays, and
 * has to: it is the only thing separating a speed from a level, so
 * "maintain 160 knots to 4 miles" is a speed on final while "maintain 160" is
 * a clearance to 16,000 ft. Dropping it silently turned one into the other.
 */
const SYNONYMS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bdegrees\b/g, ''],
  [/\bfeet\b/g, ''],
  [/\bils\b/g, 'ILS'],
  [/\bi\.? ?l\.? ?s\.?\b/g, 'ILS'],
  [/\blocaliser\b/g, 'ILS'],
  [/\blocalizer\b/g, 'ILS'],
];

/** "one zero one" arrives as "1 0 1"; glue bare digits back together. */
function joinDigits(text: string): string {
  return text.replace(/\b\d(?: \d)+\b/g, (run) => run.replace(/ /g, ''));
}

/**
 * Whole-thousand and hundred forms. Controllers say "five thousand" for
 * 5,000 and "two thousand five hundred" for 2,500; the parser wants the
 * numeral. Runs after digit folding, so the words are already numerals.
 */
function expandMagnitudes(text: string): string {
  let out = text;
  // "2 thousand 5 hundred" -> 2500
  out = out.replace(/\b(\d+) thousand (\d) hundred\b/g, (_m, k: string, h: string) =>
    String(Number(k) * 1000 + Number(h) * 100));
  out = out.replace(/\b(\d+) thousand\b/g, (_m, k: string) => String(Number(k) * 1000));
  out = out.replace(/\b(\d+) hundred\b/g, (_m, h: string) => String(Number(h) * 100));
  return out;
}

/** "flight level one five zero" -> FL150. */
function foldFlightLevel(text: string): string {
  return text.replace(/\bflight level (\d+)\b/g, (_m, n: string) => `FL${n}`);
}

/**
 * Runway designators. "runway two nine right" -> "runway 29R". Only a
 * left/right/centre that follows a runway number is a suffix — anywhere else
 * those words are turn directions, so the number has to be adjacent.
 */
function foldRunwaySuffix(text: string): string {
  return text.replace(
    /\brunway (\d{1,2}) (left|right|centre|center)\b/g,
    (_m, n: string, side: string) => {
      const letter = side === 'left' ? 'L' : side === 'right' ? 'R' : 'C';
      return `runway ${n}${letter}`;
    },
  );
}

/**
 * The callsign. Recognisers split the letters and digits apart ("AIC 101"),
 * and the parser wants them joined. Only touches the head of the line, so a
 * runway or heading later on is untouched.
 */
function joinCallsign(text: string): string {
  return text.replace(/^([A-Z]{3}) (\d{1,4})\b/, '$1$2');
}

/** Every word that can stand for a digit, for finding the callsign's end. */
const DIGIT_WORD = new RegExp(
  `^(?:\\d+|${[...DIGITS, ...CALLSIGN_ONLY_DIGITS]
    .map(([pattern]) => pattern.source.replace(/\\b/g, ''))
    .join('|')})$`,
);

/**
 * Fold the digits of the callsign, which runs from just after the airline
 * designator to the first word that cannot be a digit.
 *
 * Splitting here is what lets the aggressive homophones apply where they are
 * wanted and nowhere else: "indigo to for ate proceed direct GUDUR" has to
 * become IGO248, while the "to" in "reduce speed to 210" has to survive.
 */
function foldCallsignDigits(text: string): string {
  const words = text.split(' ');
  if (words.length < 2 || !/^[A-Z]{3}$/.test(words[0] ?? '')) return text;

  let end = 1;
  while (end < words.length && DIGIT_WORD.test(words[end] ?? '')) end += 1;
  if (end === 1) return text;

  let head = words.slice(1, end).join(' ');
  for (const [pattern, digit] of CALLSIGN_ONLY_DIGITS) head = head.replace(pattern, digit);

  return [words[0], head, ...words.slice(end)].join(' ').replace(/\s+/g, ' ');
}

/**
 * Turn one recognised utterance into a command line.
 *
 * Returns the empty string when nothing usable survives, which the caller
 * should treat as "say again" rather than as a command.
 */
export function normaliseTranscript(raw: string): string {
  let text = raw.toLowerCase().trim();
  if (text === '') return '';

  // Strip punctuation the recogniser adds; it never carries meaning here.
  text = text.replace(/[.,!?;:]/g, ' ');

  for (const [pattern, icao] of AIRLINES) text = text.replace(pattern, icao);
  text = text.replace(NOISE, ' ');
  for (const [pattern, word] of DIGITS) text = text.replace(pattern, word);
  for (const [pattern, word] of SYNONYMS) text = text.replace(pattern, word);

  text = text.replace(/\s+/g, ' ').trim();
  text = foldCallsignDigits(text);
  text = joinDigits(text);
  text = expandMagnitudes(text);
  text = foldFlightLevel(text);
  text = foldRunwaySuffix(text);

  // Collapse the whitespace all the substitution has left behind.
  text = text.replace(/\s+/g, ' ').trim();

  // The callsign is the only thing that must be upper case for the parser;
  // it upper-cases the rest itself.
  text = text.replace(/^([a-z]{3})(?=[\s\d])/, (m) => m.toUpperCase());
  text = joinCallsign(text);

  return text;
}
