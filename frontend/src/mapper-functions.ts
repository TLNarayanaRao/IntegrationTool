export type MapperFunctionDefinition = {
  name: string;
  category: "String" | "Date & Time" | "Number" | "Collection" | "Conversion" | "General" | "Encoding";
  signature: string;
  description: string;
  template: string;
  pipeline: string;
};

const fn = (category: MapperFunctionDefinition["category"], name: string, signature: string, description: string, template: string, pipeline = name): MapperFunctionDefinition => ({ category, name, signature, description, template, pipeline });

export const mapperFunctionCatalog: MapperFunctionDefinition[] = [
  fn("String", "concat", "concat(value, …values)", "Concatenate two or more values.", "concat($value, \"\")"),
  fn("String", "trim", "trim(value)", "Remove leading and trailing whitespace.", "trim($value)"),
  fn("String", "normalizeSpace", "normalizeSpace(value)", "Trim and collapse repeated whitespace.", "normalizeSpace($value)"),
  fn("String", "upperCase", "upperCase(value)", "Convert text to uppercase.", "upperCase($value)", "upperCase"),
  fn("String", "lowerCase", "lowerCase(value)", "Convert text to lowercase.", "lowerCase($value)", "lowerCase"),
  fn("String", "capitalize", "capitalize(value)", "Uppercase the first character.", "capitalize($value)"),
  fn("String", "stringLength", "stringLength(value)", "Return the number of characters.", "stringLength($value)"),
  fn("String", "substring", "substring(value, start, length?)", "Extract text using one-based positions.", "substring($value, 1, 10)", "substring(1,10)"),
  fn("String", "substringBefore", "substringBefore(value, token)", "Return text before the first token.", "substringBefore($value, \"-\")", "substringBefore(\"-\")"),
  fn("String", "substringAfter", "substringAfter(value, token)", "Return text after the first token.", "substringAfter($value, \"-\")", "substringAfter(\"-\")"),
  fn("String", "replace", "replace(value, pattern, replacement)", "Replace text using a regular expression.", "replace($value, \"old\", \"new\")", "replace(\"old\",\"new\")"),
  fn("String", "matches", "matches(value, pattern)", "Test text against a regular expression.", "matches($value, \"^[A-Z]+$\")", "matches(\"^[A-Z]+$\")"),
  fn("String", "startsWith", "startsWith(value, prefix)", "Test whether text starts with a prefix.", "startsWith($value, \"PRE\")", "startsWith(\"PRE\")"),
  fn("String", "endsWith", "endsWith(value, suffix)", "Test whether text ends with a suffix.", "endsWith($value, \"END\")", "endsWith(\"END\")"),
  fn("String", "contains", "contains(value, token)", "Test whether text contains a token.", "contains($value, \"token\")", "contains(\"token\")"),
  fn("String", "compare", "compare(value, other)", "Compare two strings and return -1, 0, or 1.", "compare($value, \"other\")", "compare(\"other\")"),
  fn("String", "translate", "translate(value, from, to)", "Translate characters by position.", "translate($value, \"abc\", \"ABC\")", "translate(\"abc\",\"ABC\")"),
  fn("String", "padLeft", "padLeft(value, width, fill?)", "Left-pad text to a fixed width.", "padLeft($value, 10, \"0\")", "padLeft(10,\"0\")"),
  fn("String", "padRight", "padRight(value, width, fill?)", "Right-pad text to a fixed width.", "padRight($value, 10, \" \")", "padRight(10,\" \")"),
  fn("String", "tokenize", "tokenize(value, pattern)", "Split text using a regular expression.", "tokenize($value, \",\")", "tokenize(\",\")"),

  fn("Date & Time", "currentDate", "currentDate()", "Current UTC date in ISO format.", "currentDate()"),
  fn("Date & Time", "currentTime", "currentTime()", "Current UTC time in ISO format.", "currentTime()"),
  fn("Date & Time", "currentDateTime", "currentDateTime()", "Current UTC timestamp in ISO format.", "currentDateTime()"),
  fn("Date & Time", "parseDate", "parseDate(value)", "Parse an ISO date or timestamp.", "parseDate($value)"),
  fn("Date & Time", "formatDate", "formatDate(value, pattern)", "Format a date with yyyy/MM/dd-style patterns.", "formatDate($value, \"yyyy-MM-dd\")", "formatDate(\"yyyy-MM-dd\")"),
  fn("Date & Time", "formatDateTime", "formatDateTime(value, pattern)", "Format a timestamp.", "formatDateTime($value, \"yyyy-MM-dd HH:mm:ss\")", "formatDateTime(\"yyyy-MM-dd HH:mm:ss\")"),
  fn("Date & Time", "addDays", "addDays(value, days)", "Add days to a date or timestamp.", "addDays($value, 1)", "addDays(1)"),
  fn("Date & Time", "addMonths", "addMonths(value, months)", "Add calendar months safely.", "addMonths($value, 1)", "addMonths(1)"),
  fn("Date & Time", "addHours", "addHours(value, hours)", "Add hours to a timestamp.", "addHours($value, 1)", "addHours(1)"),
  fn("Date & Time", "addMinutes", "addMinutes(value, minutes)", "Add minutes to a timestamp.", "addMinutes($value, 30)", "addMinutes(30)"),
  fn("Date & Time", "addSeconds", "addSeconds(value, seconds)", "Add seconds to a timestamp.", "addSeconds($value, 30)", "addSeconds(30)"),
  fn("Date & Time", "dateDifference", "dateDifference(from, to)", "Return the difference in days.", "dateDifference($value, currentDateTime())", "dateDifference(\"2026-01-01\")"),
  ...["year", "month", "day", "hour", "minute", "second"].map((name) => fn("Date & Time", name, `${name}(value)`, `Extract the ${name} component.`, `${name}($value)`)),
  fn("Date & Time", "timezoneFromDateTime", "timezoneFromDateTime(value)", "Return the timestamp timezone offset.", "timezoneFromDateTime($value)"),

  fn("Number", "number", "number(value)", "Convert a value to a number.", "number($value)"),
  fn("Number", "integer", "integer(value)", "Convert a value to an integer.", "integer($value)"),
  fn("Number", "round", "round(value, precision?)", "Round to an optional decimal precision.", "round($value, 2)", "round(2)"),
  fn("Number", "roundHalfToEven", "roundHalfToEven(value, precision?)", "Banker's rounding for financial values.", "roundHalfToEven($value, 2)", "roundHalfToEven(2)"),
  fn("Number", "floor", "floor(value)", "Round down to an integer.", "floor($value)"),
  fn("Number", "ceiling", "ceiling(value)", "Round up to an integer.", "ceiling($value)"),
  fn("Number", "abs", "abs(value)", "Return the absolute value.", "abs($value)"),
  fn("Number", "sqrt", "sqrt(value)", "Return the square root.", "sqrt($value)"),
  fn("Number", "power", "power(value, exponent)", "Raise a value to a power.", "power($value, 2)", "power(2)"),
  fn("Number", "modulo", "modulo(value, divisor)", "Return the division remainder.", "modulo($value, 2)", "modulo(2)"),
  fn("Number", "clamp", "clamp(value, minimum, maximum)", "Constrain a number to a range.", "clamp($value, 0, 100)", "clamp(0,100)"),
  ...["min", "max", "sum", "average", "count"].map((name) => fn("Number", name, `${name}(values)`, `${name[0].toUpperCase()}${name.slice(1)} collection values.`, `${name}($value)`)),

  fn("Collection", "distinctValues", "distinctValues(values)", "Remove duplicate values while preserving order.", "distinctValues($value)"),
  fn("Collection", "sort", "sort(values, descending?)", "Sort collection values.", "sort($value)"),
  fn("Collection", "reverse", "reverse(values)", "Reverse a collection or string.", "reverse($value)"),
  fn("Collection", "first", "first(values)", "Return the first value.", "first($value)"),
  fn("Collection", "last", "last(values)", "Return the last value.", "last($value)"),
  fn("Collection", "indexOf", "indexOf(values, item)", "Return the zero-based position of an item.", "indexOf($value, \"item\")", "indexOf(\"item\")"),
  fn("Collection", "subsequence", "subsequence(values, start, end?)", "Return part of a collection.", "subsequence($value, 0, 10)", "subsequence(0,10)"),
  fn("Collection", "flatten", "flatten(values)", "Flatten one level of nested arrays.", "flatten($value)"),
  fn("Collection", "join", "join(values, separator)", "Join collection values into text.", "join($value, \",\")", "join(\",\")"),
  fn("Collection", "split", "split(value, pattern)", "Split text into a collection.", "split($value, \",\")", "split(\",\")"),
  fn("Collection", "deepEqual", "deepEqual(value, other)", "Compare nested values structurally.", "deepEqual($value, $input)", "deepEqual({})"),

  fn("Conversion", "string", "string(value)", "Convert a value to text.", "string($value)"),
  fn("Conversion", "boolean", "boolean(value)", "Convert common true/false representations.", "boolean($value)"),
  fn("Conversion", "jsonParse", "jsonParse(value)", "Parse JSON text.", "jsonParse($value)"),
  fn("Conversion", "jsonRender", "jsonRender(value)", "Serialize a value as JSON.", "jsonRender($value)"),

  fn("General", "coalesce", "coalesce(value, …fallbacks)", "Return the first non-null/non-empty value.", "coalesce($value, \"fallback\")", "coalesce(\"fallback\")"),
  fn("General", "default", "default(value, fallback)", "Apply a fallback to null or empty values.", "default($value, \"fallback\")", "default(\"fallback\")"),
  fn("General", "exists", "exists(value)", "Test whether a value exists.", "exists($value)"),
  fn("General", "empty", "empty(value)", "Test whether a value is empty.", "empty($value)"),
  fn("General", "not", "not(value)", "Negate a boolean value.", "not($value)"),
  fn("General", "ifThenElse", "ifThenElse(condition, trueValue, falseValue)", "Choose between two values.", "ifThenElse($value, \"yes\", \"no\")", "ifThenElse(\"yes\",\"no\")"),
  fn("General", "uuid", "uuid()", "Generate a UUID.", "uuid()"),

  fn("Encoding", "base64Encode", "base64Encode(value)", "Encode UTF-8 text as Base64.", "base64Encode($value)"),
  fn("Encoding", "base64Decode", "base64Decode(value)", "Decode Base64 into UTF-8 text.", "base64Decode($value)"),
  fn("Encoding", "hexEncode", "hexEncode(value)", "Encode UTF-8 text as hexadecimal.", "hexEncode($value)"),
  fn("Encoding", "hexDecode", "hexDecode(value)", "Decode hexadecimal into UTF-8 text.", "hexDecode($value)"),
  fn("Encoding", "urlEncode", "urlEncode(value)", "Percent-encode text for a URL.", "urlEncode($value)"),
  fn("Encoding", "urlDecode", "urlDecode(value)", "Decode URL-encoded text.", "urlDecode($value)"),
  fn("Encoding", "hash", "hash(value, algorithm?)", "Hash text with SHA-256 or another supported algorithm.", "hash($value, \"sha256\")", "hash(\"sha256\")"),
];

export const mapperFunctionCategories = [...new Set(mapperFunctionCatalog.map((item) => item.category))];

export function functionExpression(definition: MapperFunctionDefinition, source = "${last}") {
  return definition.template.replaceAll("$value", source || "${last}");
}
