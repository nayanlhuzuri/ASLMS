export const meta = {
  name: 'team-cycle',
  description: 'One ASLMS team cycle: pick a backlog item, design (owner gate), build, test, review, document, merge',
  whenToUse: 'Invoked by /team-cycle; the owner has opted in by running that command.',
  phases: [
    { title: 'Pick', detail: 'the backlog row to work on' },
    { title: 'Design', detail: 'architect writes or refreshes the design note; stops for owner approval' },
    { title: 'Build', detail: 'developer implements the approved design on feature/<slug>' },
    { title: 'Test', detail: 'tester adds tests and reports gaps; developer fixes (max 2 rounds)' },
    { title: 'Review', detail: 'reviewer finds; developer fixes blocking findings (max 3 rounds)' },
    { title: 'Docs', detail: 'scribe updates the decisions log, schema.md, backlog, CLAUDE.md' },
    { title: 'Merge', detail: 'integrator runs the gates, squash-merges, tags, writes the report' },
  ],
}

const slugArg = args && args.slug ? String(args.slug) : null
const today = args && args.today ? String(args.today) : 'today'
const dryRun = Boolean(args && args.dryRun)

const PICK = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    title: { type: 'string' },
    status: { type: 'string' },
    note: { type: 'string' },
  },
  required: ['slug', 'status'],
}
const DESIGN = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    status: { type: 'string', description: 'awaiting-approval | blocked | approved' },
    note: { type: 'string' },
    decisions: { type: 'array', items: { type: 'string' } },
    openQuestions: { type: 'array', items: { type: 'string' } },
  },
  required: ['slug', 'status', 'note'],
}
const BUILD = {
  type: 'object',
  properties: {
    status: { type: 'string', description: 'done | blocked | failed' },
    branch: { type: 'string' },
    commits: { type: 'array', items: { type: 'string' } },
    testsSummary: { type: 'string' },
    undone: { type: 'array', items: { type: 'string' } },
    question: { type: 'string' },
  },
  required: ['status', 'branch'],
}
const GAPS = {
  type: 'object',
  properties: {
    testsAdded: { type: 'array', items: { type: 'string' } },
    testsSummary: { type: 'string' },
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        properties: { where: { type: 'string' }, problem: { type: 'string' }, fix: { type: 'string' } },
        required: ['problem'],
      },
    },
  },
  required: ['gaps'],
}
const REVIEW = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', description: 'blocking | advisory' },
          where: { type: 'string' },
          defect: { type: 'string' },
          scenario: { type: 'string' },
        },
        required: ['severity', 'defect'],
      },
    },
    testsSummary: { type: 'string' },
    mayMerge: { type: 'boolean' },
  },
  required: ['findings', 'mayMerge'],
}
const DOCS = {
  type: 'object',
  properties: { files: { type: 'array', items: { type: 'string' } }, section: { type: 'string' } },
  required: ['files'],
}
const MERGE = {
  type: 'object',
  properties: {
    merged: { type: 'boolean' },
    commit: { type: 'string' },
    tag: { type: 'string' },
    report: { type: 'string' },
    failedGate: { type: 'string' },
  },
  required: ['merged'],
}

// ------------------------------------------------------------------ Pick
phase('Pick')
const pick = await agent(
  `Read docs/backlog.md. ${slugArg ? `Return the row with slug "${slugArg}".` : 'Return the first row whose status is approved, building or review; if none, the first row with status todo or designing; if none, the first awaiting-approval or blocked row.'} If nothing matches, return slug "none" and status "none". Return slug, title, status and the design column as given.`,
  { label: 'pick backlog item', effort: 'low', schema: PICK },
)
if (!pick || pick.slug === 'none') {
  return { phase: 'Pick', outcome: 'nothing to do: no open backlog item' }
}
const slug = pick.slug
log(`Working on ${slug} (${pick.status})`)

if (pick.status === 'awaiting-approval' || pick.status === 'blocked') {
  return {
    phase: 'Pick',
    slug,
    outcome: `waiting for the owner: docs/design/${slug}.md is ${pick.status}`,
    next: pick.status === 'blocked' ? 'answer the open questions in the note, then /team-design ' + slug : '/team-approve ' + slug,
  }
}

// ------------------------------------------------------------------ Design
let designStatus = pick.status === 'approved' || pick.status === 'building' || pick.status === 'review' ? 'approved' : null
if (!designStatus) {
  phase('Design')
  const design = await agent(
    `Design the backlog item "${slug}" (${pick.title || ''}). Write docs/design/${slug}.md from docs/team/design-template.md (refresh it if it exists), set the backlog row's status and design column, and return slug, status (awaiting-approval or blocked), note path, decisions and open questions. Today is ${today}.`,
    { label: `architect: ${slug}`, agentType: 'architect', schema: DESIGN },
  )
  if (!design) return { phase: 'Design', slug, outcome: 'architect did not return' }
  return {
    phase: 'Design',
    slug,
    designStatus: design.status,
    note: design.note,
    decisions: design.decisions || [],
    openQuestions: design.openQuestions || [],
    next: design.status === 'blocked' ? 'answer the open questions in the note' : `/team-approve ${slug}`,
  }
}
if (dryRun) return { phase: 'Design', slug, outcome: 'dry run: design is approved; build not started' }

// ------------------------------------------------------------------ Build
phase('Build')
const build = await agent(
  `Build the approved design docs/design/${slug}.md on branch feature/${slug} (create it from main if missing). Follow your definition. Return status (done, blocked or failed), branch, commits, the pytest summary line, anything undone, and the question if blocked.`,
  { label: `developer: build ${slug}`, agentType: 'developer', schema: BUILD },
)
if (!build || build.status !== 'done') {
  return { phase: 'Build', slug, outcome: build ? build.status : 'developer did not return', build }
}
log(`Built on ${build.branch}: ${build.testsSummary || ''}`)

// ------------------------------------------------------------------ Test
phase('Test')
let gapsReport = null
for (let round = 1; round <= 2; round++) {
  gapsReport = await agent(
    `Branch feature/${slug}, design docs/design/${slug}.md. Add the missing tests, run the suite, commit the tests, and return the gaps for the developer (empty when ready for review).`,
    { label: `tester: round ${round}`, agentType: 'tester', schema: GAPS },
  )
  if (!gapsReport || gapsReport.gaps.length === 0) break
  log(`Tester found ${gapsReport.gaps.length} gap(s), round ${round}`)
  const fix = await agent(
    `On branch feature/${slug}, fix these gaps the tester reported, keep the suite green, commit:\n${JSON.stringify(gapsReport.gaps, null, 2)}`,
    { label: `developer: fix gaps ${round}`, agentType: 'developer', schema: BUILD },
  )
  if (!fix || fix.status !== 'done') {
    return { phase: 'Test', slug, outcome: 'developer could not close the gaps', gaps: gapsReport.gaps, fix }
  }
}

// ------------------------------------------------------------------ Review
phase('Review')
const reviewHistory = []
let review = null
for (let round = 1; round <= 3; round++) {
  review = await agent(
    `Review branch feature/${slug} for the design docs/design/${slug}.md as your definition says. Return findings (severity blocking or advisory, where, defect, scenario), the pytest summary and whether it may merge.`,
    { label: `reviewer: round ${round}`, agentType: 'reviewer', schema: REVIEW },
  )
  if (!review) return { phase: 'Review', slug, outcome: 'reviewer did not return' }
  reviewHistory.push(review)
  const blocking = review.findings.filter((f) => f.severity === 'blocking')
  if (blocking.length === 0 && review.mayMerge) break
  if (round === 3) {
    return { phase: 'Review', slug, outcome: 'blocking findings remain after three rounds', findings: review.findings }
  }
  log(`Reviewer: ${blocking.length} blocking finding(s), round ${round}`)
  const fix = await agent(
    `On branch feature/${slug}, fix these blocking review findings (and advisory ones that are cheap), keep the suite green, commit, and record any deviation in docs/design/${slug}.md:\n${JSON.stringify(blocking, null, 2)}`,
    { label: `developer: fix review ${round}`, agentType: 'developer', schema: BUILD },
  )
  if (!fix || fix.status !== 'done') {
    return { phase: 'Review', slug, outcome: 'developer could not close the findings', findings: blocking, fix }
  }
}

// ------------------------------------------------------------------ Docs
phase('Docs')
const docs = await agent(
  `Feature ${slug} on branch feature/${slug} passed tests and review. Write the documentation your definition lists (decisions log entry dated ${today}, schema.md as-built lines, backlog status "review", CLAUDE.md current focus) and commit on the branch.`,
  { label: `scribe: ${slug}`, agentType: 'scribe', schema: DOCS },
)

// ------------------------------------------------------------------ Merge
phase('Merge')
const merge = await agent(
  `Run the gates on branch feature/${slug}, squash-merge into main, tag, set the backlog row to done and write docs/reports/${today}-${slug}.md. Review findings and how they were closed:\n${JSON.stringify(reviewHistory.map((r) => r.findings).flat(), null, 2)}`,
  { label: `integrator: ${slug}`, agentType: 'integrator', schema: MERGE },
)

return {
  phase: 'Merge',
  slug,
  build: { branch: build.branch, commits: build.commits, tests: build.testsSummary },
  tests: gapsReport ? { added: gapsReport.testsAdded, summary: gapsReport.testsSummary } : null,
  review: review ? { findings: review.findings, mayMerge: review.mayMerge } : null,
  docs: docs ? docs.files : null,
  merge,
  outcome: merge && merge.merged ? `merged as ${merge.commit}; report ${merge.report}` : `not merged: ${merge ? merge.failedGate : 'integrator did not return'}`,
}
