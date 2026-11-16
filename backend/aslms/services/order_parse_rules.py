"""The patterns and phrase tables of the order reader (design `order-sections`, decisions 7, 11, 12, 15 and 17).

Pure Python (`re` only): no model, no model library, no database and no network, as `next_date_rules.py`. Each pattern
names the variant of the Gauhati High Court's order template it covers; the shares quoted are those measured on the dev
database on 15 Nov 2026 (259,432 order texts) where the design gives one. Every match is case-insensitive and tolerant
of extra spaces. The reader itself is `services/order_parse.py`."""

from __future__ import annotations

import re

# bump to re-read every order gradually (decision 18); the old readings stay, marked `parser_version`
PARSER_VERSION = 1
# an interim order's body at most this long may be procedural (decision 15)
PROCEDURAL_MAX_CHARS = 1500
# text beyond this is not read; the reading is flagged `capped` (decision 15)
MAX_PARSE_CHARS = 2_000_000
# the CNR line, the citation line and the court header are looked for in the first lines only
HEADER_SCAN_LINES = 16
# `Case No. :` is looked for in the first lines only
CASE_NO_SCAN_LINES = 40
# the heading is looked for within this many non-blank lines after the coram (judgments put the advocates and the
# judgment dates between them)
HEADING_SCAN_LINES = 40
# the order date and the author within this many non-blank lines after the heading (or after the coram of an
# off-template order)
DATE_SCAN_LINES = 4
# the opening part only among the first paragraphs; a conclusion phrase only from this share of the body on
OPENING_PARAGRAPHS = 3
CONCLUSION_FROM_SHARE = 0.5
# the trailer within this many lines of the end (a digital signature's block may follow it)
TRAILER_SCAN_LINES = 15
# the closing `Date:` of a judgment within this many lines before the sign-off
CLOSING_DATE_LINES = 12
# a new paragraph of an unnumbered body after a line ending a sentence shorter than this share of the median line
SHORT_LINE_SHARE = 0.7
# text kept for a direction's sentence, an author, a case name, a heading, an addressee and printed values
DIRECTION_TEXT_MAX = 1000
AUTHOR_MAX = 200
CASE_NAME_MAX = 200
HEADING_MAX = 80
ADDRESSEE_MAX = 200
CASE_NO_MAX = 80
OUTCOME_TEXT_MAX = 1000
# the window before a main-matter subject in which an interlocutory word disqualifies it
SUBJECT_LOOKBACK = 40
# the window before a citation in which its "X v. Y" case name may stand
CASE_NAME_LOOKBACK = 260

I = re.IGNORECASE
M = re.MULTILINE

# a date as printed: 29.07.2026, 29-07-2026, 29/07/2026, and broken across lines ("29.07." / "2026")
DATE = r"(?P<d>\d{1,2})\s*[./-]\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<y>(?:19|20)\d{2})"
DATE_RE = re.compile(DATE)

# ------------------------------------------------------------------------------------------------ the template (7)

# (1) `Page No.# n/N` at a page's top (about 97% of orders carry them), and `Page n of N` of judgments typed outside
# the court's template
PAGE_MARK = re.compile(
    r"^[\f \t]*Page\s*(?:No\.?\s*#?\s*(\d{1,4})\s*/\s*\d{1,4}|(\d{1,4})\s+of\s+\d{1,4})[ \t]*$", I | M
)
# (2) the CNR line: 16 characters (`GAHC010121712025`)
CNR_LINE = re.compile(r"^\s*([A-Z]{4}\d{12})\s*$", I)
# (2) the stray `undefined` on line 3 of most orders
UNDEFINED = re.compile(r"^\s*undefined\s*$", I)
# (2) a judgment's own neutral citation in the place of `undefined` (`2026:GAU-AS:7666`)
NEUTRAL_CITATION = re.compile(r"^\s*(\d{4}:GAU-[A-Z]{2,3}:\d{1,7})\s*$", I)
# (3) the court header and its bracketed line
COURT_HEADER = re.compile(r"^\s*THE\s+GAUHATI\s+HIGH\s+COURT\b", I)
COURT_HEADER_SUB = re.compile(r"^\s*\(\s*HIGH\s+COURT\s+OF\s+ASSAM\b.*\)?\s*$", I)
# (4) `Case No. : WP(C)/5797/2023`
CASE_NO = re.compile(r"^\s*Case\s*No\.?\s*:\s*(.*?)\s*$", I)
# (6) `Advocate for the Petitioner :`, `Advocate for :`, lower case, and the `For the Petitioner(s) :` form of judgments
ADVOCATES = re.compile(
    r"^\s*(?:Advocates?\s+for\b|For\s+the\s+[A-Za-z/()., -]{2,60}?:|For\s+(?:the\s+)?"
    r"(?:petitioners?|respondents?|appellants?|applicants?|accused|complainants?|caveators?|state|opposite)\b)",
    I,
)
# (7) `Linked Case : RSA/255/2019`, its case number sometimes blank
LINKED_CASE = re.compile(r"^\s*Linked\s+Case\s*:\s*(.*?)\s*$", I)
# the separator line of a linked-case block
RULE_LINE = re.compile(r"^\s*-{4,}\s*$")
# (8) the coram marker alone on its line: `BEFORE`, `:::BEFORE:::`, `B E F O R E` (with stray characters around it),
# `CORAM`, `PRESENT`
CORAM_MARK = re.compile(r"^[^A-Za-z0-9]*(?:B\s*E\s*F\s*O\s*R\s*E|C\s*O\s*R\s*A\s*M|PRESENT)[^A-Za-z0-9]*$", I)
# (8) the marker with the bench on the same line (`CORAM : HON'BLE MR. JUSTICE …`)
CORAM_INLINE = re.compile(r"^[^A-Za-z0-9]*(?:BEFORE|CORAM|PRESENT)\s*[:\-]+\s*(\S.*)$", I)
# (8) a judge's or registrar's line: `HONOURABLE`, `HON'BLE` (the apostrophe often lost), `JUSTICE`, `REGISTRAR`
JUDGE_LINE = re.compile(r"HON\W{0,3}BLE|HONOU?RABLE|\bJUSTICE\b|\bREGISTRAR\b", I)
# (8) the Lawazima court: a Deputy, Joint or Assistant Registrar presiding
REGISTRAR_CORAM = re.compile(r"\bREGISTRAR\b", I)
# (9) the judgment block: `Date on which judgment is reserved :`, `Date of pronouncement of judgment :`, the
# operative-part and full-pronouncement lines, and `Date of Hearing :` / `Date of Judgment :`
JUDGMENT_DATE_LINE = re.compile(r"^\s*Date\s+(?:of|on\s+which)\b[^:\n]{0,140}?:?\s*" + DATE, I)
RESERVED_WORDS = re.compile(r"\breserv", I)
PRONOUNCED_WORDS = re.compile(r"pronounce|date\s+of\s+(?:the\s+)?judg?e?ment", I)
OPERATIVE_WORDS = re.compile(r"operative", I)
# (10) the heading: `ORDER`, `JUDGMENT`, `JUDGMENT & ORDER`, `JUDGMENT&ORDER`, `JUDGMENT AND ORDER`, `JUDGEMENT`,
# `COMMON ORDER`, with `[ORAL]` / `(ORAL)` and `(CAV)`, and an author in brackets on the same line
HEADING = re.compile(
    # indented or not, letters spaced out (`O R D E R`), a date before it on the same line (`29.05.2024   O R D E R`)
    r"^\s*(?:(?P<date>"
    + DATE
    + r")\s+)?[^A-Za-z0-9(\[\s]{0,3}\s*(?P<h>(?:COMMON\s+)?(?:J\s*U\s*D\s*G\s*E?\s*M\s*E\s*N\s*T"
    r"(?:\s*(?:&|AND)\s*O\s*R\s*D\s*E\s*R)?|O\s*R\s*D\s*E\s*R))\s*"
    r"(?P<rest>(?:\[\s*ORAL\s*\]|\(\s*ORAL\s*\)|\(\s*C\.?\s?A\.?\s?V\.?\s*\)|\s)*)"
    r"(?P<author>\((?:[^()]|\([^()]*\)){2,200}\))?[^A-Za-z0-9]{0,3}\s*$",
    I,
)
ORAL = re.compile(r"ORAL", I)
CAV = re.compile(r"C\.?\s?A\.?\s?V", I)
JUDGMENT_WORD = re.compile(r"J\s?U\s?D\s?G", I)
# (11) the order date line: `29.07.2026`, `Date : 29.07.2026` (registrar orders), `Dated 29-07-2026`
DATE_LINE = re.compile(r"^[^A-Za-z0-9]*(?:Dated?[\s:\-\u2013]*)?" + DATE + r"[^A-Za-z0-9]*$", I)
# (11) a date broken across two lines: `29.07.` / `2026`
DATE_HEAD = re.compile(r"^[^A-Za-z0-9]*(?:Dated?[\s:\-\u2013]*)?\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]?\s*$", I)
DATE_TAIL = re.compile(r"^\s*[./-]?\s*(?:19|20)\d{2}[^A-Za-z0-9]*$")
# (12) the author: `(N. Unni Krishnan Nair, J)`, `(Ashutosh Kumar, C.J.)`, `Per …`
AUTHOR = re.compile(r"^\s*[(\[]\s*(?:Per\s+)?((?:[^()\[\]]|\([^()]*\)){2,200}?)\s*[)\]]\s*$", I)
# (10) a heading printed one letter or two per line (`O    R` / `D` / `E` / `R`)
VERTICAL_PIECE = re.compile(r"^\s*[A-Za-z](?:\s+[A-Za-z])?\s*$")
VERTICAL_WORDS = frozenset({"ORDER", "JUDGMENT", "JUDGEMENT"})
AUTHOR_PER = re.compile(r"^\s*Per\s+([A-Z][^\n]{1,200}?)\s*[:,.\-]?\s*$")
AUTHOR_JUDGE = re.compile(r"(?:\bJ\.?|C\.\s?J\.?|\bJJ\.?|JUSTICE)\s*$", I)
# (14) the sign-off words: `JUDGE`, `JUDGE  JUDGE`, `CHIEF JUSTICE` (broken over lines), `DEPUTY REGISTRAR`,
# `Joint Registrar (Judicial)`
SIGNOFF_LINE = re.compile(
    r"^[^A-Za-z0-9]*(?:(?:JUDGES?|CHIEF|JUSTICE|DEPUTY|JOINT|ASSISTANT|ADDL\.?|ADDITIONAL|ACTING|REGISTRAR|"
    r"\(?\s*JUDICIAL\s*\)?|\(?\s*JUDL\.?\s*\)?|\(?\s*BENCH\s*\)?|\(?\s*VIGILANCE\s*\)?|SD/?-?)[^A-Za-z0-9]*)+$",
    I,
)
SIGNOFF_WORD = re.compile(r"JUDGE|JUSTICE|REGISTRAR", I)
# (14) the trailer
TRAILER = re.compile(r"^\s*Comparing\s+Assistant\s*$", I)

# ------------------------------------------------------------------------------------------------ paragraphs (11)

# a printed paragraph number at the line start: `2.`, `2)`, `(2)`, `2.1`, `[2]`
PARA_START = re.compile(
    r"^\s*(?P<label>\d{1,3}(?:\.\d{1,2})+\.?(?=\s)|\d{1,3}[.)](?=\s)|\(\d{1,3}\)(?=\s)|\[\d{1,3}\])\s*"
)
# a sub-list item: `i)`, `(ii)`, `(a)`, only after a line ending in `:` or `;`
SUBLIST_START = re.compile(r"^\s*(?P<label>\(?(?:[ivxlc]{1,6}|[a-z])\))\s+", I)
LIST_INTRO_END = re.compile(r"[:;]\s*-?\s*$")
# a number at a line start that only continues a reference on the line before ("respondent No." / "3.")
REFERENCE_END = re.compile(
    r"\b(?:No|Nos|Section|Sections|Rule|Rules|Article|Articles|para|paragraph|dated)\.?\s*$", I
)
SENTENCE_END = re.compile(r"[.?!:;\"'”’)\]]\s*$")
SHORT_LINE_END = re.compile(r"[.:?]\s*$")

# ------------------------------------------------------------------------------------------------ parts (12)

PART_BODY = "body"
PART_OPENING = "opening"
PARTS = (
    PART_BODY,
    PART_OPENING,
    "facts",
    "petitioner_submissions",
    "respondent_submissions",
    "issues",
    "reasoning",
    "conclusion",
)
# a paragraph opening with a heading word
PART_HEADINGS = (
    ("facts", re.compile(r"^(?:brief\s+)?facts?\b(?:\s+of\s+the\s+case)?\s*[:.\-]?", I)),
    ("facts", re.compile(r"^background\b", I)),
    (
        "petitioner_submissions",
        re.compile(
            r"^(?:submissions?|arguments?)\s+(?:of|on\s+behalf\s+of)\s+the\s+(?:petitioner|appellant|applicant)s?",
            I,
        ),
    ),
    (
        "respondent_submissions",
        re.compile(
            r"^(?:submissions?|arguments?)\s+(?:of|on\s+behalf\s+of)\s+the\s+(?:respondent|state)s?", I
        ),
    ),
    ("petitioner_submissions", re.compile(r"^(?:submissions?|arguments?|contentions?)\b", I)),
    (
        "issues",
        re.compile(
            r"^(?:issues?|points?\s+for\s+(?:determination|consideration)|questions?\s+for\s+consideration)\b",
            I,
        ),
    ),
    (
        "reasoning",
        re.compile(r"^(?:discussion|analysis|consideration|findings?|reasons?|determination)\b", I),
    ),
    ("conclusion", re.compile(r"^(?:conclusions?|result|order|directions?|relief)\s*[:.\-]?\s*$", I)),
    ("conclusion", re.compile(r"^(?:conclusions?|directions?)\b", I)),
)
# the court's standard phrases, looked for near the paragraph's start (the first PHRASE_WINDOW characters)
PHRASE_WINDOW = 220
OPENING_PHRASES = re.compile(
    r"^(?:heard\b|(?:none|nobody)\s+appears|(?:mr|ms|mrs|dr)\.?\s+[^.]{0,80}?learned\s+(?:senior\s+)?counsel\s+"
    r"(?:is\s+present|appears|appearing))",
    I,
)
PART_PHRASES = (
    (
        "facts",
        re.compile(
            r"\bthe\s+(?:brief\s+)?facts?\s+(?:of\s+the\s+case|in\s+brief|leading|giving\s+rise|necessary|relevant|requisite|as\s+projected)|\bthe\s+case\s+of\s+the\s+(?:petitioner|appellant|applicant|prosecution)s?\b",
            I,
        ),
    ),
    (
        "petitioner_submissions",
        re.compile(
            r"learned\s+(?:senior\s+)?counsel\s+(?:appearing\s+)?(?:for|on\s+behalf\s+of)\s+the\s+(?:petitioner|appellant|applicant|accused)s?[^.]{0,120}?\b(?:submits?|submitted|contends?|contended|argues?|argued|urges?|urged)\b",
            I,
        ),
    ),
    (
        "respondent_submissions",
        re.compile(
            r"learned\s+(?:senior\s+)?(?:standing\s+counsel|government\s+advocate|govt\.?\s+advocate|additional\s+advocate\s+general|advocate\s+general|additional\s+public\s+prosecutor|public\s+prosecutor|addl\.?\s+p\.?\s?p\.?|p\.?\s?p\.?|counsel\s+(?:appearing\s+)?(?:for|on\s+behalf\s+of)\s+the\s+(?:respondent|state|opposite\s+part)[a-z]*)[^.]{0,160}?\b(?:submits?|submitted|contends?|contended|argues?|argued|urges?|urged|opposes?|opposed|supports?|supported)\b",
            I,
        ),
    ),
    (
        "issues",
        re.compile(
            r"\bthe\s+(?:short\s+|only\s+|main\s+|moot\s+)?(?:issue|question|point)s?\s+(?:that\s+|which\s+)?(?:arises?|arising|falls?|for\s+(?:consideration|determination)|to\s+be\s+(?:decided|determined|considered))",
            I,
        ),
    ),
    (
        "reasoning",
        re.compile(
            r"^(?:(?:i|we)\s+have\s+(?:heard|considered|perused|gone\s+through|given)|having\s+(?:heard|considered|perused)|on\s+(?:a\s+)?(?:careful\s+)?(?:consideration|perusal))\b",
            I,
        ),
    ),
    (
        "conclusion",
        re.compile(
            r"^(?:in\s+view\s+of\s+the\s+(?:above|foregoing|discussion|reasons?|facts)|for\s+the\s+(?:reasons?|foregoing)|accordingly\b|in\s+the\s+result\b|in\s+the\s+light\s+of\s+the\s+(?:above|foregoing)|resultantly\b|consequently\b|in\s+the\s+premises\b|with\s+the\s+(?:above|aforesaid)\s+(?:observations?|directions?))",
            I,
        ),
    ),
)

# ------------------------------------------------------------------------------------------------ tags (15)

SUBSTANTIVE_PHRASES = re.compile(
    r"interim\s+(?:relief|protection)|interim\s+order\b[^.]{0,80}?\b(?:extended|vacated|continue)|\bstay(?:ed)?\b|"
    r"status\s+quo|shall\s+not\b|\bbail\b|\bsuspended\b|set\s+aside|\bquash(?:ed)?\b|"
    r"is\s+directed\s+to\s+(?!(?:file|produce|place|obtain|take|submit|furnish)\b)",
    I,
)

# ------------------------------------------------------------------------------------------------ facts (17)

# the main matter, never an interlocutory application, a Misc. Case or an I.A.
MAIN_MATTER_SUBJECTS = (
    r"(?:writ\s+petitions?|writ\s+appeals?|(?:criminal\s+|civil\s+|first\s+|second\s+|regular\s+|misc(?:ellaneous)?\.?\s+)?appeals?"
    r"|(?:criminal\s+|civil\s+|review\s+|revision\s+|election\s+|company\s+|transfer\s+|bail\s+)?petitions?"
    r"|(?:criminal\s+|civil\s+)?revisions?|review(?:\s+applications?)?|bail\s+applications?|cases?"
    r"|contempt(?:\s+(?:petitions?|cases?|proceedings?|applications?))?|proceedings?|matters?|references?"
    r"|applications?\s+under\s+(?:section|article|order|rule)s?\b(?:[^.;\n]|\.(?=\S)){0,60}?)"
)
INTERLOCUTORY = re.compile(
    r"\b(?:I\.?\s?A\b\.?|interlocutory|interim|misc(?:ellaneous)?\.?\s*(?:\(\s*\w+\s*\)\s*)?cases?|M\.?\s?C\b\.?|"
    r"connected|condonation)",
    I,
)
_GAP = r"(?P<gap>(?:[^.;\n]|\.(?=\S)){0,100}?)"
_BE = r"\b(?:is|are|stands?|shall\s+stand|be|been|was|were|hereby)\s+(?:(?!not\b)\w+\s+){0,3}?"
OUTCOME_VERBS = (
    ("withdrawn", r"(?:dismissed\s+as\s+withdrawn|withdrawn|allowed\s+to\s+be\s+withdrawn)"),
    (
        "partly_allowed",
        r"(?:partly\s+allowed|partially\s+allowed|allowed\s+in\s+part|allowed\s+partly|allowed\s+to\s+the\s+extent)",
    ),
    ("disposed_of", r"disposed\s+of+"),
    ("dismissed", r"dismissed"),
    ("allowed", r"allowed"),
    ("closed", r"(?:closed|dropped)"),
)
OUTCOME_PATTERNS = tuple(
    (
        value,
        re.compile(
            r"\b(?P<subj>" + MAIN_MATTER_SUBJECTS + r")\b" + _GAP + _BE + r"(?P<verb>" + verb + r")\b", I
        ),
    )
    for value, verb in OUTCOME_VERBS
)
# "permitted to withdraw the writ petition"
WITHDRAW_PATTERN = re.compile(
    r"\b(?:permitted|allowed|granted\s+liberty)\s+to\s+withdraw\s+(?:the\s+|this\s+|instant\s+|present\s+)*"
    r"(?P<subj>" + MAIN_MATTER_SUBJECTS + r")\b",
    I,
)
NEGATION = re.compile(r"\bnot\b|\bcannot\b|\bnever\b", I)

DIRECTION_VERBS = re.compile(
    r"\b(?:(?:is|are)\s+(?:hereby\s+|also\s+|further\s+|accordingly\s+)?directed\s+to|shall\b(?!\s+be\s+(?:at\s+liberty|free|"
    r"entitled|open|deemed|treated|subject))|(?:is|are)\s+(?:hereby\s+)?required\s+to|to\s+consider\s+and\s+dispose\s+of|"
    r"to\s+pass\s+(?:an?\s+|appropriate\s+|necessary\s+)?(?:reasoned\s+|speaking\s+)?orders?|do\s+the\s+needful)",
    I,
)
DIRECT_ADDRESSEE = re.compile(r"\bdirect(?:s|ed)?\s+(?:the\s+)?", I)
ADDRESSEES = re.compile(
    r"\b(?:the\s+)?(?:(?:State|official|concerned|private)\s+)?(?:respondents?(?:\s+(?:authorit(?:y|ies)|"
    r"Nos?\.?\s*\d+(?:\s*(?:,|and|&|to|-)\s*\d+)*))?|"
    r"State\s+(?:Government|of\s+Assam|respondents?|appellants?|authorities)|"
    # the State, never "State counsel" or another State's name
    r"(?-i:State)\b(?!\s+(?:of\s+(?!Assam)|counsel|Counsel))|"
    r"Government(?!\s+(?:Advocate|Pleader|Counsel))(?:\s+of\s+(?:Assam|India))?|"
    r"(?:competent|concerned|appropriate|appellate|disciplinary|district|revenue|police|prosecuting|licensing|selection)"
    r"\s+authorit(?:y|ies)|authorit(?:y|ies)\s+concerned|authorit(?:y|ies)|Union\s+of\s+India|"
    # titles only with their capital letter ("the principal amount" is not an addressee)
    r"(?-i:Commissioner(?:\s+(?:and|&)\s+Secretary)?|(?:Principal\s+|Additional\s+Chief\s+|Chief\s+|"
    r"Joint\s+|Deputy\s+|Under\s+)?Secretary|Director(?:\s+General(?:\s+of\s+Police)?)?|Deputy\s+Commissioner|"
    r"District\s+(?:Magistrate|Collector|Commissioner|Education\s+Officer)|Superintendent\s+of\s+Police|"
    r"Officer[\s-]+in[\s-]+charge|Inspector\s+General|Collector|Board|Corporation|Department|Municipal\s+[A-Z]\w+|"
    r"Inspector\s+of\s+Schools|Principal|Registrar\s+of\s+[A-Z]\w+|Election\s+Commission))\b",
    I,
)
DIRECTION_SPAN = 160  # characters between the addressee and the verb
PROCEDURAL_DIRECTION_ACTS = re.compile(
    r"\b(?:file|filing|submit|furnish)\s+(?:(?:an?|the|its|their|his|her|fresh|additional|better|counter|reply|further|"
    r"proper|separate|detailed|own|necessary)\s+){0,3}(?:affidavits?|counter|reply|objections?|reports?|status\s+reports?|"
    r"written\s+statements?|documents?|statements?|instructions?|records?|case\s+diary)|"
    r"\bproduc(?:e|ing)\s+(?:the\s+)?(?:\w+\s+){0,3}?(?:records?|case\s+diary|documents?)|"
    r"\b(?:obtain|seek|take|get)\s+(?:\w+\s+){0,2}?instructions?|\bplace\s+(?:the\s+)?(?:\w+\s+){0,3}?records?|"
    r"\bcase\s+diary|\bsteps?\s+for\s+service",
    I,
)
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-one": 21,
    "thirty": 30, "forty": 40, "forty-five": 45, "sixty": 60, "ninety": 90, "hundred": 100,
}  # fmt: skip
_NUMBER = r"\d{1,3}|" + "|".join(sorted((re.escape(w) for w in NUMBER_WORDS), key=len, reverse=True))
PERIOD = re.compile(
    r"\bwithin\s+(?:a\s+(?:(?:further|maximum|outer)\s+)?period\s+of\s+|a\s+further\s+period\s+of\s+|a\s+further\s+|"
    r"the\s+next\s+)?(?P<n>"
    + _NUMBER
    + r")(?:\s*\(\s*[A-Za-z\- ]{2,20}\s*\))?\s+(?P<unit>days?|weeks?|months?)\b"
    r"(?:\s+(?:from|of|after)\s+(?P<from>(?:[^.;,\n]|\.(?=\S)){1,100}))?",
    I,
)
FROM_ORDER_DATE = re.compile(
    r"^(?:today|now|the\s+date\s+hereof|(?:the\s+)?date\s+of\s+(?:this|the\s+present|passing\s+of\s+(?:this|the))\s+"
    r"(?:order|judg?e?ment)|(?:the\s+)?passing\s+of\s+(?:this|the)\s+(?:order|judg?e?ment)|this\s+(?:order|judg?e?ment))",
    I,
)
FROM_RECEIPT = re.compile(
    r"receipt|production|service|served|communicat|furnish|certified\s+copy|presentation|submission|copy\s+of",
    I,
)

# acts and provisions (decision 17)
_PROV = r"\d{1,4}[A-Z]{0,3}(?:\s*\(\s*[0-9A-Za-z]{1,5}\s*\))*"
_PROVS = _PROV + r"(?:\s*(?:,|/|&|\band\b|\bor\b|r/w|\bread\s+with\b|\bto\b)\s*" + _PROV + r")*"
_WORD = r"(?:\(?[A-Z][\w.'&()\-]*|of|and|the|for|in|on|to|&)"
_ACT_NAME = (
    r"(?=[A-Z])(?:"
    + _WORD
    + r"\s+){1,10}?(?:Act|Code|Sanhita|Adhiniyam|Ordinance|Regulations?)\b(?:\s*,?\s*(?:19|20)\d{2})?"
)
_SHORT = (
    r"(?:Indian\s+Penal\s+Code|Code\s+of\s+Criminal\s+Procedure|Code\s+of\s+Civil\s+Procedure|"
    r"Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|Bharatiya\s+Nyaya\s+Sanhita|Bharatiya\s+Sakshya\s+Adhiniyam|"
    r"N\.?\s?D\.?\s?P\.?\s?S\.?\s+Act|I\.?\s?P\.?\s?C\b\.?|Cr\.?\s?P\.?\s?C\b\.?|C\.?\s?P\.?\s?C\b\.?|B\.?\s?N\.?\s?S\.?\s?S\b\.?|"
    r"B\.?\s?N\.?\s?S\b\.?|B\.?\s?S\.?\s?A\b\.?)(?:\s*,\s*(?:19|20)\d{2})?"
)
ACT_PATTERNS = (
    (
        "section",
        re.compile(
            r"\b(?:Sections?|Secs?\.?|u/s\.?|S\.)\s*(?P<prov>"
            + _PROVS
            + r")\s*(?:of\s+(?:the\s+)?)?(?P<act>"
            + _SHORT
            + r")",
            I,
        ),
    ),
    (
        "section",
        re.compile(
            r"\b(?i:Sections?|Secs?\.?|u/s\.?)\s*(?P<prov>"
            + _PROVS
            + r")\s+of\s+(?:the\s+)?(?P<act>"
            + _ACT_NAME
            + r")"
        ),
    ),
    (
        "article",
        re.compile(
            r"\bArticles?\s*(?P<prov>"
            + _PROVS
            + r")\s+of\s+(?:the\s+)?(?P<act>Constitution(?:\s+of\s+India)?)",
            I,
        ),
    ),
    (
        "rule",
        re.compile(
            r"\b(?i:Rules?)\s*(?P<prov>"
            + _PROVS
            + r")\s+of\s+(?:the\s+)?(?P<act>(?=[A-Z])(?:"
            + _WORD
            + r"\s+){1,10}?Rules?\b(?:\s*,?\s*(?:19|20)\d{2})?)"
        ),
    ),
    (
        "order",
        re.compile(
            r"\b(?P<prov>Order\s+(?:[IVXL]{1,6}|\d{1,2})\s*,?\s*Rules?\s+\d{1,3}[A-Z]?(?:\s*\(\s*\w{1,4}\s*\))*)\s*"
            r"(?:of\s+(?:the\s+)?)?(?P<act>Code\s+of\s+Civil\s+Procedure(?:\s*,\s*1908)?|C\.?\s?P\.?\s?C\b\.?)",
            I,
        ),
    ),
)

# judgments cited (decision 17): the reporters seen in the dev orders
REPORTER_PATTERNS = (
    (
        "SCC OnLine",
        re.compile(r"\b(?P<year>(?:19|20)\d{2})\s+SCC\s+On\s?Line\s+[A-Z][A-Za-z.]{1,12}\s+\d{1,6}\b", I),
    ),
    ("SCC", re.compile(r"\(\s*(?P<year>(?:19|20)\d{2})\s*\)\s*\d{1,2}\s+SCC\s+\d{1,4}\b")),
    ("AIR", re.compile(r"\bAIR\s+(?P<year>(?:19|20)\d{2})\s+[A-Z][A-Za-z.]{1,12}\s+\d{1,5}\b")),
    ("SCR", re.compile(r"\(\s*(?P<year>(?:19|20)\d{2})\s*\)\s*\d{1,2}\s+SCR\s+\d{1,5}\b")),
    ("GLT", re.compile(r"\b(?P<year>(?:19|20)\d{2})\s*\(\s*\d{1,2}\s*\)\s*GLT\s+\d{1,5}\b")),
    ("GLR", re.compile(r"\(\s*(?P<year>(?:19|20)\d{2})\s*\)\s*\d{1,2}\s+GLR\s+\d{1,5}\b")),
    ("GauLT", re.compile(r"\b(?P<year>(?:19|20)\d{2})\s*\(\s*\d{1,2}\s*\)\s*GauLT\s+\d{1,5}\b", I)),
    ("LLJ", re.compile(r"\(\s*(?P<year>(?:19|20)\d{2})\s*\)\s*(?:\d{1,2}|I{1,3}|IV)\s+LLJ\s+\d{1,5}\b")),
    ("INSC", re.compile(r"\b(?P<year>(?:19|20)\d{2})\s+INSC\s+\d{1,5}\b")),
    ("neutral", re.compile(r"\b(?P<year>(?:19|20)\d{2}):[A-Z]{2,6}(?:-[A-Z]{2,4})?:\d{1,7}\b")),
)
CASE_NAME = re.compile(
    # the last boundary before the name (the greedy lead), so the name is the shortest "X v. Y" that ends at the citation
    r"^.*(?:^|[;:\[\]\(\)]|\.\s|\b(?:in|on|upon|see)\s|\bcase\s+of\s|\bcalled\s)\s*(?P<name>(?-i:[A-Z])[^;:\[\]]{0,200}?\s"
    r"(?:v\.?|vs\.?|versus)\s[^;:\[\]]{1,200}?)[\s,]*(?:reported\s+in|\(|\[|,)?\s*$",
    I | re.DOTALL,
)

# sentence ends that are not: abbreviations before a full stop
ABBREVIATIONS = frozenset(
    "no nos mr mrs ms dr sri smt shri hon honble rs sec secs art arts vs v viz ie eg etc ltd co st jr sr govt dept "
    "addl spl crl misc cont cas para paras pp p j cj jj ors anr u s r o s/o d/o w/o vill dist p.o p.s ps po "
    "md mst mustt late lt col gen capt prof".split()
)  # fmt: skip
