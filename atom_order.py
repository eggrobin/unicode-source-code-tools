import codecs
import regex
import sys
import unicodedata

sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# For some reason the regex module does not support
# \p{Bidi_Paired_Bracket_Type=Close}, so we grab this
# from https://util.unicode.org/UnicodeJsps/regex.jsp?a=%5Cp%7BBidi_Paired_Bracket_Type%3DClose%7D&b=.
CLOSING_BRACKETS = frozenset(")]}༻༽᚜⁆⁾₎⌉⌋〉❩❫❭❯❱❳❵⟆⟧⟩⟫⟭⟯⦄⦆⦈⦊⦌⦎⦐⦒⦔⦖⦘⧙⧛⧽⸣⸥⸧⸩⹖⹘⹚⹜〉》」』】〕〗〙〛﹚﹜﹞）］｝｠｣")

IDENTIFIER_OR_KEYWORD=(r"(?:(r)(#))?([_\p{XID_Start}]\p{XID_Continue}*)",)
COMMENT=(
  r"(//)([^\n]*)",  # Line comment.
  r"(/\*)((?:(?R)|[^*]|\*(?!/))*)(\*/)",  # Block comment.
)
STRINGY=(
  r"(b)?(')([^\\']|\\(?:'|[^']+))(')",  # Character and byte literals.
  r'(b)?(")((?:[^\\"]|\\.)*)(")',  # Strings and byte strings.
  r'(r)(?<delimiter>#+)(")((?:[^"]|"(?!\g<delimiter>))*)(")(\g<delimiter>)',  # Raw strings.
)
NUMERIC=(
  r"([0-9][.\p{XID_Continue}]*)",
)

with open(sys.argv[1], encoding="utf-8") as f:
  contents = f.read()

fix = "fix" in sys.argv[2:]

atoms = []

try:
  while contents:
    found_token = None
    token_atoms = None
    for candidates, mnemonic in ((IDENTIFIER_OR_KEYWORD, "I"),
                                 (COMMENT, "C"),
                                 (STRINGY, "S"),
                                 (NUMERIC, "N")):
      for candidate in candidates:
        try:
          match = regex.match("^" + candidate, contents)
        except:
          print(candidate)
          raise
        if match:
          if found_token:
            raise ValueError("Ambiguous between %s and %s at %s" % (found_token, mnemonic, contents[:30]))
          found_token = mnemonic
          token_atoms = tuple(group for group in match.groups() if group)
          length = match.span()[1]
          if "".join(token_atoms) != contents[:length]:
            raise ValueError("Bad groups in %s: %s into %s" % (found_token, contents[:length], token_atoms))

    if not found_token:
      c = contents[0]
      if regex.match(r"\p{Pattern_White_Space}", c):
        found_token = " "
      elif regex.match(r"\p{Pattern_Syntax}", c):
        found_token = "X"
      else:
        raise ValueError("Unexpected character %s at %s" % (c, contents[:30]))
      length = 1
      token_atoms = (c,)

    if found_token == " " and unicodedata.category(c) == "Cf":
       print("Discarding " + unicodedata.name(c))
    else:
      for atom in token_atoms:
        atoms.append((atom, found_token))
      if found_token not in (" ", "X"):
        atoms.append(("", "B"))
    contents = contents[length:]
except:
  print(contents[:30], found_token)
  raise

column = 0
lrm_insertion_point = 0
source_line = ""
key_line = ""
last_strong_column = -1
last_strong = None
atom_boundaries_since_last_strong = 0

def bidi_overview(s):
  result = ""
  for c in s:
    if ord(c) > 128 or (c >= "A" and c <= "Z"):
      bidi_class = unicodedata.bidirectional(c)
      if len(bidi_class) == 1:
        result += bidi_class
      elif bidi_class == "AL":
        result += "R"
      else:
        result += "U"
    else:
      result += c
  return result

fixed_source = ""

for atom, mnemonic,  in atoms:
  atom_boundaries_since_last_strong = 1
  if mnemonic == "B":
    lrm_insertion_point = column
  for i, c in enumerate(atom):
    bidi_class = unicodedata.bidirectional(c)

    if c == "\n":
      fixed_source += source_line + c
      column = 0
      source_line = ""
      key_line = ""
      last_strong_column = -1
      last_strong = None
      atom_boundaries_since_last_strong = 0
      continue
    column += 1
    source_line += c
    key_line += mnemonic if i in (0, len(atom) - 1) else "_"

    if (last_strong in ("R", "AL") and
        (bidi_class in ("EN", "AN", "R", "AL") or
         c in CLOSING_BRACKETS) and
        atom_boundaries_since_last_strong):
      # The span between the last strong and the current character is going to
      # be RTL (or at least might be, in the closing blacket case, depending on
      # pairing). If there is an atom boundary in there, we have a problem.
      print("Possible reordering on the following line:")
      print(last_strong_column * " " + (column - last_strong_column) * "_")
      print(bidi_overview(source_line))
      print(key_line)
      if lrm_insertion_point >= last_strong_column:
        fixed_source_line = source_line[:lrm_insertion_point] + "\u200E" + source_line[lrm_insertion_point:]
        fixed_key_line = key_line[:lrm_insertion_point] + " " + key_line[lrm_insertion_point:]
        print("Can be fixed by LRM insertion:")
        print(lrm_insertion_point * " " + "|")
        print(bidi_overview(fixed_source_line))
        print(fixed_key_line)
        if fix:
          source_line = fixed_source_line
          key_line = fixed_key_line
          last_strong = "L"
          last_strong_column = lrm_insertion_point
          column += 1
      else:
        print("Unfixable in plain text")

    if bidi_class in ("L", "R", "AL"):
      last_strong = bidi_class
      last_strong_column = column
      atom_boundaries_since_last_strong = 0

if source_line:
  fixed_source += source_line + c

with open(sys.argv[1], mode="w", encoding="utf-8") as f:
  f.write(fixed_source)
