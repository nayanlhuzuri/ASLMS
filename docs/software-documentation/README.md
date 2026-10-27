# Software documentation

`docs/ASLMS_Software_Documentation.docx` is the software documentation for Government submission: an application brochure followed by the formal documentation (sections 1 to 13 and Annexures A to D). It is text only, with no screenshots.

`build.js` generates it with the `docx` npm package (9.5.x). `ref.json` holds the user types and functions read from the reference data on 27 Oct 2026. To regenerate:

```
npm install docx@9.5.1
node build.js ../ASLMS_Software_Documentation.docx
```

The contents page numbers are fixed in `TOC_PAGES` in `build.js`; check them against a rendered copy after any change.
