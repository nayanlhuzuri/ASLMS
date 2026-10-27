# Hosting guide

`docs/ASLMS_Hosting_Guide.docx` is the step-by-step hosting guide for the data-centre system administrators: Part 1, the one-VM pilot on Rocky Linux 9 (the current plan); Part 2, full hosting for about 1,000 users (after the pilot is approved, rows 192 and 194); moving from one VM to many; the installer (rows 193 and 194, planned); releases and patch updates; checklists and annexures.

`build.js` generates it with the `docx` npm package (9.5.x). `switch.md` holds the court-data switch prefix the guide prints in its commands (documentation may show the runbook's command line; code and configuration never carry it). Contents page numbers come from `toc.json`, which `toc.py` writes from a rendered PDF:

```
npm install docx@9.5.1
node build.js ../ASLMS_Hosting_Guide.docx
# render to PDF, then: python toc.py ASLMS_Hosting_Guide.pdf '<json list of headings>' > toc.json, and build again
```
