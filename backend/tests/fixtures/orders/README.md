Masked copies of real Gauhati High Court orders for the order reader's tests (design `order-sections`, decision 24).
Every personal name (parties, advocates, judges, officers) and every address is replaced, and the digits of the CNR and
the case number are masked (`GAHC01XXXXXX2025`, `WP(C)/XXXX/2025`); the tests put a synthetic CNR in place of the mask
where they need one. `<FF>` stands for the form feed that text extraction writes between two pages (`"\n\f"`). The
court, the case types, years, dates, acts and cited judgments are kept.

`off_template_linked.txt` (a `whole` order with two `Linked Case :` blocks and no coram) and `first_page_unmarked.txt`
(a first page printed without a marker, then `Page No.# 2/3`) are built on the same masks for parser version 2
(design `order-sections-review-advisories`, decisions 3 and 4). `linked_v1.json` is the version 1 reader's
`linked_cases` of every earlier fixture, which version 2 must keep.
