import codecs
import regex
import sys
import unicodedata

sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# For some reason the regex module does not support
# \p{Bidi_Paired_Bracket_Type=Close}, so we grab this
# from https://util.unicode.org/UnicodeJsps/regex.jsp?a=%5Cp%7BBidi_Paired_Bracket_Type%3DClose%7D&b=.
CLOSING_BRACKETS = frozenset(")]}༻༽᚜⁆⁾₎⌉⌋〉❩❫❭❯❱❳❵⟆⟧⟩⟫⟭⟯⦄⦆⦈⦊⦌⦎⦐⦒⦔⦖⦘⧙⧛⧽⸣⸥⸧⸩⹖⹘⹚⹜〉》」』】〕〗〙〛﹚﹜﹞）］｝｠｣")

class Atom:
  def __init__(self, atom):
    self.text = atom
    self.can_insert_lrm_after = False

class Consumable:
  def __init__(self, atoms):
    self.atoms = atoms

  @classmethod
  def accept(cls, text):
    match = cls.pattern.match(text)
    if match:
      length = match.span()[1]
      atoms = tuple(Atom(group) for group in match.groups() if group)
      if "".join(atom.text for atom in atoms) != contents[:length]:
        raise ValueError(
          "Bad groups in %s: %s is not a partition of %s" % (
            cls.__name__, atoms, contents[:length]))
      return cls(atoms)

  def __repr__(self):
    return "%s(%r)" % (type(self).__name__, self.atoms)

class Token(Consumable):
  def __init__(self, atoms):
    self.atoms = atoms
    atoms[-1].can_insert_lrm_after = True

class IdentifierOrKeyword(Token):
  mnemonic = "I"
  pattern = regex.compile(r"^(?:(r)(#))?([_\p{XID_Start}]\p{XID_Continue}*)")
  
class Comment(Token):
  mnemonic = "C"
  pattern = regex.compile("|".join((
      r"^(//)([^\n]*)",  # Line comment.
      r"^(/\*)((?:(?R)|[^*]|\*(?!/))*)(\*/)",  # Block comment.
  )))

  def __init__(self, atoms):
    self.atoms = atoms
    atoms[-1].can_insert_lrm_after = True
    atoms[0].can_insert_lrm_after = True

class Stringy(Token):
  mnemonic = "S"
  pattern = regex.compile("|".join((
      r"^(b)?(')([^\\']|\\(?:'|[^']+))(')",  # Character and byte literals.
      r'^(b)?(")((?:[^\\"]|\\.)*)(")',  # Strings and byte strings.
      r'^(r)(?<delimiter>#+)(")((?:[^"]|"(?!\g<delimiter>))*)(")(\g<delimiter>)',  # Raw strings.
  )))

class Numeric(Token):
  mnemonic = "N"
  pattern = regex.compile(r"^([0-9][.\p{XID_Continue}]*)")

class UnlexedSyntax(Consumable):
  mnemonic = "X"
  pattern = regex.compile(r"^(\p{Pattern_Syntax})")

class UnlexedWhitespace(Consumable):
  mnemonic = " "
  pattern = regex.compile(r"^(\p{Pattern_White_Space})")

with open(sys.argv[1], encoding="utf-8") as f:
  contents = f.read()

original = contents

fix = "fix" in sys.argv[2:]

tokens = []

try:
  while contents:
    found_token = None
    for token_class in Token.__subclasses__():
      token = token_class.accept(contents)
      if token:
        if found_token:
          raise ValueError("Ambiguous between %s and %s at %s" % (found_token, token, contents[:30]))
        found_token = token

    if not found_token:
      for unlexed in (UnlexedSyntax, UnlexedWhitespace):
        token = unlexed.accept(contents)
        if token:
          found_token = token

    if not found_token:
      raise ValueError("No token found " +contents[:30])

    if isinstance(found_token, UnlexedWhitespace) and unicodedata.category(found_token.atoms[0].text) == "Cf":
       print("Discarding " + unicodedata.name(found_token.atoms[0].text))
    else:
      tokens.append(found_token)
    length = sum(len(atom.text) for atom in found_token.atoms)
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

for token in tokens:
  for atom in token.atoms:
    atom_boundaries_since_last_strong = 1
    for i, c in enumerate(atom.text):
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
      key_line += token.mnemonic if i in (0, len(atom.text) - 1) else "_"

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
          last_strong = "L"
          if fix:
            source_line = fixed_source_line
            key_line = fixed_key_line
            last_strong_column = lrm_insertion_point
            column += 1
        else:
          print("Unfixable in plain text")

      if bidi_class in ("L", "R", "AL"):
        last_strong = bidi_class
        last_strong_column = column
        atom_boundaries_since_last_strong = 0
  if atom.can_insert_lrm_after:
    lrm_insertion_point = column

if source_line:
  fixed_source += source_line + c

with open(sys.argv[1], mode="w", encoding="utf-8") as f:
  f.write(fixed_source)

if original == fixed_source:
  print("No change")
