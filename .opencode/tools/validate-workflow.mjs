import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const artifactFiles = ['artifacts/requirement-review.md', 'artifacts/jira-tasks.md', 'artifacts/qase-test-model.md'];
const artifactKeys = ['requirement_review', 'jira_tasks', 'qase_model'];
const statuses = ['NOT_RUN', 'PASS', 'FAIL', 'BLOCKED'];
const sourceKey = source => JSON.stringify([source?.type, source?.identity, source?.version ?? null, source?.content_sha256 ?? null]);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isoTime = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const nonempty = value => typeof value === 'string' && value.trim().length > 0;

// JSON preserves exact text (including CRLF and trailing whitespace) inside Markdown.
export function composeInput(snapshot) {
  if (!record(snapshot) || snapshot.format !== 'workflow-input-v1' || !nonempty(snapshot.original_text) ||
      !Array.isArray(snapshot.clarifications) || !snapshot.clarifications.every(c => record(c) && nonempty(c.identity) && nonempty(c.text)) ||
      new Set(snapshot.clarifications.map(c => c.identity)).size !== snapshot.clarifications.length) {
    throw new Error('invalid workflow input snapshot');
  }
  return snapshot.original_text + snapshot.clarifications.map(c => `\n\nУточнение ${c.identity}:\n${c.text}`).join('');
}
export const inputHash = text => createHash('sha256').update(text, 'utf8').digest('hex');

export function readInputSnapshot(ref, read) {
  if (typeof ref !== 'string' || !/^artifacts\/requirement-review\.md#[a-z0-9-]+$/.test(ref)) throw new Error('invalid source input_ref');
  const [file, anchor] = ref.split('#');
  const content = read(file);
  if (typeof content !== 'string') throw new Error('missing input snapshot file');
  const parts = content.split(`<a id="${anchor}"></a>`);
  if (parts.length !== 2 || !/(?:^|\n)##[ \t]+[^\n]+\r?\n(?:[ \t]*\r?\n)*$/.test(parts[0])) throw new Error('missing or ambiguous input snapshot anchor');
  const section = parts[1].split(/\r?\n##(?:[ \t]+|$)/)[0];
  const blocks = [...section.matchAll(/^```workflow-input\r?\n([^\r\n]+)\r?\n```[ \t]*\r?$/gm)];
  if (blocks.length !== 1) throw new Error('missing or ambiguous workflow-input block');
  let snapshot;
  try { snapshot = JSON.parse(blocks[0][1]); } catch { throw new Error('invalid input snapshot JSON'); }
  const text = composeInput(snapshot);
  if (!record(snapshot.source) || !['type', 'identity', 'version'].every(k => Object.hasOwn(snapshot.source, k))) throw new Error('missing snapshot source');
  return { snapshot, text, sha256: inputHash(text) };
}

export function compareInputs(previous, current) {
  return {
    source_changed: previous.snapshot.source.type !== current.snapshot.source.type || previous.snapshot.source.identity !== current.snapshot.source.identity,
    version_changed: previous.snapshot.source.version !== current.snapshot.source.version,
    original_text_changed: previous.snapshot.original_text !== current.snapshot.original_text,
    clarifications_changed: JSON.stringify(previous.snapshot.clarifications) !== JSON.stringify(current.snapshot.clarifications),
    content_changed: previous.text !== current.text,
    previous_sha256: previous.sha256,
    current_sha256: current.sha256
  };
}

export function validateWorkflow(state, read) {
  const errors = [];
  const check = (ok, message) => { if (!ok) errors.push(message); };
  if (!record(state)) return ['state must be an object'];
  const containers = ['source', 'gates', 'gate_reviews', 'blocking_finding_details', 'active_artifacts'];
  containers.forEach(key => check(record(state[key]), `invalid ${key}: expected object`));
  check(Array.isArray(state.blocking_findings) && state.blocking_findings.every(nonempty), 'invalid blocking_findings: expected string array');
  check(typeof state.next_stage === 'string', 'invalid next_stage: expected string');
  if (errors.length) return errors;
  const readLocal = file => {
    try { return read(file); }
    catch { errors.push(`cannot read local file: ${file}`); return null; }
  };
  const checkEvidence = (refs, context) => {
    if (!Array.isArray(refs)) return;
    refs.filter(nonempty).forEach(ref => {
      // External evidence is not fetched by this structural validator.
      if (/^https?:\/\//.test(ref)) return;
      const [file, anchor, extra] = ref.split('#');
      if (!file || path.posix.isAbsolute(file) || file.includes('\\') || file.split('/').includes('..') || file.includes(':') || extra !== undefined || (anchor !== undefined && !/^[a-z0-9-]+$/.test(anchor))) {
        errors.push(`invalid local evidence reference: ${context}: ${ref}`); return;
      }
      const content = readLocal(file);
      if (typeof content !== 'string') { errors.push(`missing local evidence file: ${context}: ${ref}`); return; }
      if (anchor !== undefined) {
        const matches = content.split('\n').filter(line => line.trim() === `<a id="${anchor}"></a>`);
        check(matches.length === 1, `missing or ambiguous evidence anchor: ${context}: ${ref}`);
      }
    });
  };
  check(state.schema_version === 1, 'unsupported schema_version');
  check(nonempty(state.run_id), 'missing run_id');
  check(['product', 'resume', 'audit', 'maintenance'].includes(state.run_type), 'invalid run_type');
  const source = state.source;
  check(record(source) && ['type', 'identity', 'version', 'content_sha256', 'confirmed', 'confirmed_at'].every(k => Object.hasOwn(source, k)), 'missing source fields');
  check(source?.confirmed_at === null || isoTime(source?.confirmed_at), 'invalid confirmation time');
  if (source?.confirmed === true) check(isoTime(source.confirmed_at) && (typeof source.content_sha256 === 'string' && /^[a-f0-9]{64}$/.test(source.content_sha256)), 'confirmed source requires time and hash');
  check(['Confluence', 'user_text'].includes(source?.type), 'unsupported source type');
  check(nonempty(source?.identity), 'missing source identity');
  check(source?.version == null || (Number.isInteger(source.version) && source.version > 0) || nonempty(source?.version), 'invalid source version');
  check(source?.content_sha256 == null || (typeof source.content_sha256 === 'string' && /^[a-f0-9]{64}$/.test(source.content_sha256)), 'invalid content hash');
  check(typeof source?.confirmed === 'boolean', 'missing source confirmation state');
  check(Object.hasOwn(source, 'input_ref'), 'missing source input_ref field');
  if (source.input_ref != null) {
    try {
      const input = readInputSnapshot(source.input_ref, readLocal);
      check(JSON.stringify([input.snapshot.source.type, input.snapshot.source.identity, input.snapshot.source.version]) === JSON.stringify([source.type, source.identity, source.version]), 'snapshot source mismatch');
      check(source.content_sha256 === input.sha256, 'source content hash mismatch');
    } catch (error) { errors.push(error.message); }
  } else {
    check(source.confirmed === false && source.content_sha256 === null, 'confirmed/hashed source requires input snapshot');
  }

  const gates = [1, 2, 3].map(i => state.gates?.[`gate_${i}`]);
  gates.forEach((g, i) => check(statuses.includes(g), `invalid gate_${i + 1}`));
  gates.forEach((g, i) => {
    if (g === 'PASS') check(gates.slice(0, i).every(x => x === 'PASS'), `gate_${i + 1} PASS requires preceding PASS`);
  });
  const findings = state.blocking_findings;
  check(Array.isArray(findings) && findings.every(nonempty), 'invalid blocking_findings');
  const gateReviews = state.gate_reviews;
  check(record(gateReviews) && [1, 2, 3].every(i => {
    const review = gateReviews?.[`gate_${i}`];
    return record(review) && nonempty(review.owner) && nonempty(review.reviewer) && isoTime(review.decision_at) && Array.isArray(review.evidence_refs) && review.evidence_refs.length > 0 && review.evidence_refs.every(nonempty);
  }), 'invalid gate_reviews');
  check(record(gateReviews) && Object.keys(gateReviews).every(k => /^gate_[123]$/.test(k)), 'unknown gate review');
  const findingDetails = state.blocking_finding_details;
  check(record(findingDetails) && (findings ?? []).every(id => {
    const detail = findingDetails?.[id];
    return record(detail) && nonempty(detail.owner) && nonempty(detail.reviewer) && isoTime(detail.decision_at) && Array.isArray(detail.evidence_refs) && detail.evidence_refs.length > 0 && detail.evidence_refs.every(nonempty);
  }), 'invalid blocking_finding_details');
  check(record(findingDetails) && Object.keys(findingDetails).every(id => (findings ?? []).includes(id)), 'orphan blocking_finding_details');
  Object.entries(gateReviews).forEach(([key, value]) => checkEvidence(value?.evidence_refs, key));
  Object.entries(findingDetails).forEach(([key, value]) => checkEvidence(value?.evidence_refs, key));
  if (gates.every(g => g === 'PASS')) check(findings?.length === 0, 'PASS cannot retain blocking findings');
  const routes = {
    requirements_review: gates.every(g => g === 'NOT_RUN'),
    gate_1: gates.every(g => g === 'NOT_RUN'),
    jira_tasks: gates[0] === 'PASS' && gates.slice(1).every(g => g === 'NOT_RUN'),
    gate_2: gates[0] === 'PASS' && gates.slice(1).every(g => g === 'NOT_RUN'),
    qase_model: gates[0] === 'PASS' && gates[1] === 'PASS' && gates[2] === 'NOT_RUN',
    gate_3: gates[0] === 'PASS' && gates[1] === 'PASS' && gates[2] === 'NOT_RUN',
    completed: gates.every(g => g === 'PASS'),
    requirements_clarification: ['NOT_RUN', 'BLOCKED', 'FAIL'].includes(gates[0]) && !gates.slice(1).includes('PASS'),
    blocked: gates.some(g => ['BLOCKED', 'FAIL'].includes(g))
  };
  check(Object.hasOwn(routes, state.next_stage) && routes[state.next_stage], 'next_stage is not permitted by gates');
  if (!['blocked', 'requirements_clarification'].includes(state.next_stage) || gates.includes('PASS')) {
    check(source?.confirmed === true && nonempty(source?.confirmed_at) && Number.isFinite(Date.parse(source.confirmed_at)) && (typeof source?.content_sha256 === 'string' && /^[a-f0-9]{64}$/.test(source.content_sha256)), 'progress/PASS requires confirmed source and content hash');
  }
  if (!['blocked', 'requirements_clarification'].includes(state.next_stage)) check(findings?.length === 0, 'progress cannot retain blocking findings');
  const active = state.active_artifacts;
  check(record(active) && artifactKeys.every(k => Object.hasOwn(active, k)), 'missing active artifact slots');
  artifactKeys.forEach((key, i) => {
    const pointer = active?.[key];
    const required = gates[i] !== 'NOT_RUN' || state.next_stage === `gate_${i + 1}`;
    if (pointer == null) { check(!required, `missing active artifact: ${key}`); return; }
    if (typeof pointer !== 'string') { errors.push(`invalid pointer: ${key}`); return; }
    const [file, anchor, extra] = pointer.split('#');
    if (file !== artifactFiles[i] || !/^[a-z0-9-]+$/.test(anchor ?? '') || extra !== undefined) {
      errors.push(`invalid pointer: ${key}`); return;
    }
    const content = readLocal(file);
    if (typeof content !== 'string') { errors.push(`missing artifact: ${key}`); return; }
    const marker = `<a id="${anchor}"></a>`;
    const parts = content.split(marker);
    if (parts.length !== 2) { errors.push(`missing or ambiguous active section: ${key}`); return; }
    check(/(?:^|\n)##[ \t]+[^\n]+\r?\n(?:[ \t]*\r?\n)*$/.test(parts[0]), `active anchor must follow level-2 heading: ${key}`);
    const section = parts[1].split(/\r?\n##(?:[ \t]+|$)/)[0];
    const metadata = [...section.matchAll(/<!-- workflow-review\s+([^\n]+?)\s*-->/g)];
    if (metadata.length !== 1) { errors.push(`missing or ambiguous review metadata: ${key}`); return; }
    let review;
    try { review = JSON.parse(metadata[0][1]); } catch { errors.push(`invalid review JSON: ${key}`); return; }
    if (!review || typeof review !== 'object' || Array.isArray(review)) { errors.push(`invalid review object: ${key}`); return; }
    check(review.run_id === state.run_id, `run_id mismatch: ${key}`);
    check(record(review.source) && ['type', 'identity', 'version', 'content_sha256'].every(k => Object.hasOwn(review.source, k)), `missing review source fields: ${key}`);
    check(sourceKey(review.source) === sourceKey(source), `source mismatch: ${key}`);
    check(Object.hasOwn(review.source ?? {}, 'input_ref') && review.source.input_ref === source.input_ref, `source input_ref mismatch: ${key}`);
    check(review.gate === `gate_${i + 1}` && review.status === gates[i], `gate mismatch: ${key}`);
    check(nonempty(review.reason), `missing review reason: ${key}`);
    check(nonempty(review.owner) && nonempty(review.reviewer) && isoTime(review.decision_at) && Array.isArray(review.evidence_refs) && review.evidence_refs.length > 0 && review.evidence_refs.every(nonempty), `missing review accountability fields: ${key}`);
    const stateReview = gateReviews[`gate_${i + 1}`];
    for (const field of ['owner', 'reviewer', 'decision_at']) {
      check(review[field] === stateReview?.[field], `review ${field} mismatch: ${key}`);
    }
    const refs = value => Array.isArray(value) && value.every(nonempty) ? [...new Set(value)].sort() : null;
    check(JSON.stringify(refs(review.evidence_refs)) === JSON.stringify(refs(stateReview?.evidence_refs)), `review evidence_refs mismatch: ${key}`);
    checkEvidence(review.evidence_refs, key);
    if (gates[i] !== 'NOT_RUN') check(review.decision_by === 'qa-orchestrator', `missing orchestrator decision: ${key}`);
    const labelText = section.split('\n').map(line => line.replace(/^\*\*(Текущий Gate #\d+: (?:NOT_RUN|PASS|FAIL|BLOCKED))\.\*\*\s*$/, '$1')).join('\n');
    const labels = [...labelText.matchAll(new RegExp(`^Текущий Gate #${i + 1}: (NOT_RUN|PASS|FAIL|BLOCKED)[ \\t]*\\r?$`, 'gm'))];
    check(labels.length === 1 && labels[0][1] === gates[i], `current gate label mismatch: ${key}`);
  });
  const audit = readLocal('artifacts/audit-log.md');
  check(typeof audit === 'string' && audit.split('\n').some(line => line.startsWith('| ') && line.split('|')[1]?.trim() === state.run_id), 'missing audit row for current run');
  return errors;
}

function selfTest() {
  const source = { type: 'user_text', identity: 'user supplied requirements', version: null, content_sha256: inputHash('Requirements\n'), input_ref: 'artifacts/requirement-review.md#input-fixture', confirmed: true, confirmed_at: '2026-09-09T07:00:00Z' };
  const accountability = { owner: 'qa-orchestrator', reviewer: 'qa-lead', decision_at: '2026-09-09T07:00:00Z', evidence_refs: ['artifacts/audit-log.md'] };
  const base = { schema_version: 1, run_id: 'test-run', run_type: 'product', source, gates: { gate_1: 'PASS', gate_2: 'PASS', gate_3: 'PASS' }, gate_reviews: { gate_1: accountability, gate_2: accountability, gate_3: accountability }, next_stage: 'completed', active_artifacts: {}, blocking_findings: [], blocking_finding_details: {} };
  const files = { 'artifacts/audit-log.md': '| test-run | time | verified |' };
  artifactKeys.forEach((key, i) => {
    base.active_artifacts[key] = `${artifactFiles[i]}#current`;
    files[artifactFiles[i]] = `## Current\n<a id="current"></a>\n<!-- workflow-review ${JSON.stringify({ run_id: base.run_id, source, gate: `gate_${i + 1}`, status: 'PASS', decision_by: 'qa-orchestrator', owner: 'qa-orchestrator', reviewer: 'qa-lead', decision_at: '2026-09-09T07:00:00Z', evidence_refs: ['artifacts/audit-log.md'], reason: 'fixture review' })} -->\nТекущий Gate #${i + 1}: PASS\n`;
  });
  const snapshotBlock = `\n## Input fixture\n<a id="input-fixture"></a>\n\`\`\`workflow-input\n${JSON.stringify({ format: 'workflow-input-v1', source: { type: source.type, identity: source.identity, version: source.version }, original_text: 'Requirements\n', clarifications: [] })}\n\`\`\`\n`;
  files[artifactFiles[0]] += snapshotBlock;
  let count = 0;
  function test(name, mutate, pass = false) {
    const state = structuredClone(base), texts = { ...files };
    mutate(state, texts);
    assert.equal(validateWorkflow(state, p => texts[p]).length === 0, pass, name); count++;
  }
  test('confirmed text without page/version', () => {}, true);
  test('blocked gates cannot route to Qase', s => { Object.keys(s.gates).forEach(k => s.gates[k] = 'BLOCKED'); s.next_stage = 'qase_model'; });
  test('PASS disagrees with active BLOCKED', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replaceAll('PASS', 'BLOCKED'); });
  test('missing anchor', s => { s.active_artifacts.requirement_review = `${artifactFiles[0]}#missing`; });
  test('wrong run', s => { s.run_id = 'other-run'; });
  test('wrong source', s => { s.source.identity = 'other source'; });
  test('unknown gate', s => { s.gates.gate_1 = 'OK'; });
  test('unknown route', s => { s.next_stage = 'qase'; });
  test('missing artifact', (s, f) => { delete f[artifactFiles[2]]; });
  test('historical PASS cannot satisfy current section', (s, f) => { f[artifactFiles[0]] += '\n## Current\n<a id="new"></a>\nТекущий Gate #1: BLOCKED'; s.active_artifacts.requirement_review = `${artifactFiles[0]}#new`; });
  test('unconfirmed source', s => { s.source.confirmed = false; });
  test('blockers with completed', s => { s.blocking_findings = ['AMB-1']; });
  test('missing run type', s => { delete s.run_type; });
  test('orphan blocker detail', s => { s.blocking_finding_details = { 'AMB-1': { owner: 'owner', reviewer: 'reviewer', decision_at: '2026-09-09T07:00:00Z', evidence_refs: ['artifacts/audit-log.md'] } }; });
  test('first launch without downstream artifacts', (s, f) => { s.next_stage = 'requirements_review'; artifactKeys.forEach((k, i) => { s.gates[`gate_${i+1}`] = 'NOT_RUN'; s.active_artifacts[k] = null; if (i === 0) f[artifactFiles[i]] = snapshotBlock; else delete f[artifactFiles[i]]; }); }, true);
  test('gate review requires draft', s => { s.next_stage = 'gate_3'; s.gates.gate_3 = 'NOT_RUN'; s.active_artifacts.qase_model = null; });
  test('missing audit', (s, f) => { f['artifacts/audit-log.md'] = 'run_id=historical'; });
  test('malformed metadata', (s, f) => { f[artifactFiles[0]] = '<a id="current"></a>\n<!-- workflow-review null -->'; });
  test('contradictory visible status', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('Текущий Gate #1: PASS', 'Текущий Gate #1: BLOCKED'); });
  test('duplicate active anchor', (s, f) => { f[artifactFiles[0]] += '<a id="current"></a>'; });
  test('subagent cannot issue final gate decision', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('qa-orchestrator', 'requirements-reviewer'); });
  test('valid transition to Jira without Qase artifact', (s, f) => {
    s.next_stage = 'jira_tasks';
    [1, 2].forEach(i => { s.gates[`gate_${i+1}`] = 'NOT_RUN'; s.active_artifacts[artifactKeys[i]] = null; delete f[artifactFiles[i]]; });
  }, true);
  test('valid blocked local review without confirmed source', (s, f) => {
    s.source.confirmed = false; s.source.content_sha256 = null; s.source.confirmed_at = null; s.source.input_ref = null;
    s.next_stage = 'requirements_clarification'; s.blocking_findings = ['AMB-1'];
    s.blocking_finding_details = { 'AMB-1': { owner: 'product-owner', reviewer: 'qa-lead', decision_at: '2026-09-09T07:00:00Z', evidence_refs: ['artifacts/audit-log.md'] } };
    artifactKeys.forEach((key, i) => {
      s.gates[`gate_${i+1}`] = 'BLOCKED';
      const review = { run_id: s.run_id, source: s.source, gate: `gate_${i+1}`, status: 'BLOCKED', decision_by: 'qa-orchestrator', owner: 'qa-orchestrator', reviewer: 'qa-lead', decision_at: '2026-09-09T07:00:00Z', evidence_refs: ['artifacts/audit-log.md'], reason: 'pending clarification' };
      f[artifactFiles[i]] = `## Current\n<a id="current"></a>\n<!-- workflow-review ${JSON.stringify(review)} -->\nТекущий Gate #${i+1}: BLOCKED`;
    });
  }, true);
  test('anchor without heading', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('## Current\n', ''); });
  test('anchor under wrong heading level', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('## Current', '### Current'); });
  test('text between heading and anchor', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('## Current\n', '## Current\nUnrelated text\n'); });
  test('status must occupy whole line', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('Текущий Gate #1: PASS', 'Текущий Gate #1: PASS_WITH_ERRORS'); });
  test('quoted status is not decision', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('Текущий Gate #1:', '> Текущий Gate #1:'); });
  test('missing source version', s => { delete s.source.version; });
  test('missing confirmation timestamp', s => { delete s.source.confirmed_at; });
  test('non ISO timestamp', s => { s.source.confirmed_at = 'September 9, 2026'; });
  test('blockers cannot advance to Jira', (s, f) => {
    s.next_stage = 'jira_tasks'; s.blocking_findings = ['GAP-1'];
    [1, 2].forEach(i => { s.gates[`gate_${i+1}`] = 'NOT_RUN'; s.active_artifacts[artifactKeys[i]] = null; delete f[artifactFiles[i]]; });
  });
  test('CRLF artifacts', (s, f) => { artifactFiles.forEach(p => { f[p] = f[p].replaceAll('\n', '\r\n'); }); }, true);
  test('existing bold decision format', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('Текущий Gate #1: PASS', '**Текущий Gate #1: PASS.**'); }, true);
  test('metadata cannot omit null version', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('"version":null,', ''); });
  test('next section cannot supply decision', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('<!-- workflow-review', '##\tOther section\n<!-- workflow-review'); });
  const changeReview = (texts, mutate) => {
    texts[artifactFiles[0]] = texts[artifactFiles[0]].replace(/<!-- workflow-review (.+) -->/, (_, json) => {
      const review = JSON.parse(json); mutate(review);
      return `<!-- workflow-review ${JSON.stringify(review)} -->`;
    });
  };
  const rejects = (name, mutate, expected) => {
    const state = structuredClone(base), texts = { ...files };
    mutate(state, texts);
    const errors = validateWorkflow(state, p => texts[p]);
    assert(errors.some(error => error.includes(expected)), `${name}: ${JSON.stringify(errors)}`);
    count++;
  };
  for (const field of ['owner', 'reviewer', 'decision_at']) {
    rejects(`state ${field} differs from artifact`, s => {
      s.gate_reviews.gate_1[field] = field === 'decision_at' ? '2026-09-10T07:00:00Z' : 'other-person';
    }, `review ${field} mismatch`);
    rejects(`artifact ${field} differs from state`, (s, f) => changeReview(f, r => {
      r[field] = field === 'decision_at' ? '2026-09-10T07:00:00Z' : 'other-person';
    }), `review ${field} mismatch`);
  }
  rejects('different valid evidence references', (s, f) => {
    f['artifacts/other.md'] = 'evidence';
    s.gate_reviews.gate_1.evidence_refs = ['artifacts/other.md'];
  }, 'review evidence_refs mismatch');
  rejects('missing state evidence file', s => {
    s.gate_reviews.gate_1.evidence_refs = ['artifacts/missing.md'];
  }, 'missing local evidence file');
  rejects('missing artifact evidence file', (s, f) => changeReview(f, r => {
    r.evidence_refs = ['artifacts/missing.md'];
  }), 'missing local evidence file');
  rejects('missing evidence anchor', s => {
    s.gate_reviews.gate_1.evidence_refs = ['artifacts/audit-log.md#missing'];
  }, 'missing or ambiguous evidence anchor');
  rejects('duplicate evidence anchor', (s, f) => {
    s.gate_reviews.gate_1.evidence_refs = ['artifacts/audit-log.md#proof'];
    f['artifacts/audit-log.md'] += '\n<a id="proof"></a>\n<a id="proof"></a>';
  }, 'missing or ambiguous evidence anchor');
  rejects('blocker evidence also checked', s => {
    s.blocking_findings = ['AMB-1'];
    s.blocking_finding_details = { 'AMB-1': { ...accountability, evidence_refs: ['artifacts/missing.md'] } };
  }, 'missing local evidence file');
  for (const ref of ['../outside.md', '/outside.md', 'artifacts/audit-log.md#', 'artifacts/audit-log.md#a#b']) {
    rejects(`invalid local evidence ${ref}`, s => { s.gate_reviews.gate_1.evidence_refs = [ref]; }, 'invalid local evidence reference');
  }
  test('valid anchors and reordered evidence sets', (s, f) => {
    const refs = ['artifacts/audit-log.md#proof', 'https://example.test/evidence'];
    f['artifacts/audit-log.md'] += '\n<a id="proof"></a>\nEvidence';
    s.gate_reviews = structuredClone(s.gate_reviews);
    s.gate_reviews.gate_1 = { ...s.gate_reviews.gate_1, evidence_refs: refs };
    changeReview(f, r => { r.evidence_refs = [...refs].reverse(); });
  }, true);
  for (const value of [null, {}, 'AMB-1', 3, [null], [{}]]) {
    rejects(`invalid findings ${JSON.stringify(value)}`, s => { s.blocking_findings = value; }, 'invalid blocking_findings');
  }
  for (const key of ['source', 'gates', 'gate_reviews', 'blocking_finding_details', 'active_artifacts']) {
    for (const value of [null, [], 'invalid', 4]) {
      rejects(`invalid container ${key} ${JSON.stringify(value)}`, s => { s[key] = value; }, `invalid ${key}`);
    }
  }
  rejects('invalid route object', s => { s.next_stage = { toString: 1 }; }, 'invalid next_stage');
  rejects('invalid hash object', s => { s.source.content_sha256 = { toString: 1 }; }, 'invalid content hash');
  rejects('invalid nested gate review', s => { s.gate_reviews.gate_1 = null; }, 'invalid gate_reviews');
  rejects('invalid nested artifact evidence', (s, f) => changeReview(f, r => { r.evidence_refs = {}; }), 'missing review accountability fields');
  assert(validateWorkflow(null, () => null).includes('state must be an object')); count++;
  const readErrors = validateWorkflow(structuredClone(base), () => { throw new Error('private details'); });
  assert(readErrors.some(error => error.startsWith('cannot read local file:')));
  assert(!readErrors.some(error => error.includes('private details'))); count++;
  const mutateSnapshot = (texts, mutate) => {
    texts[artifactFiles[0]] = texts[artifactFiles[0]].replace(/(```workflow-input\r?\n)([^\r\n]+)/, (_, prefix, json) => {
      const snapshot = JSON.parse(json); mutate(snapshot); return prefix + JSON.stringify(snapshot);
    });
  };
  test('confirmed composed input validates with exact whitespace', (s, f) => {
    mutateSnapshot(f, r => {
      r.original_text = 'Исходный текст  \r\n';
      r.clarifications = [{ identity: 'C-1', text: 'Подтверждено\n' }];
    });
    s.source.content_sha256 = readInputSnapshot(s.source.input_ref, p => f[p]).sha256;
    artifactFiles.forEach(file => {
      f[file] = f[file].replace(/<!-- workflow-review (.+) -->/, (_, json) => {
        const review = JSON.parse(json); review.source.content_sha256 = s.source.content_sha256;
        return `<!-- workflow-review ${JSON.stringify(review)} -->`;
      });
    });
  }, true);
  rejects('confirmed source without snapshot', s => { s.source.input_ref = null; }, 'requires input snapshot');
  rejects('missing input_ref field', s => { delete s.source.input_ref; }, 'missing source input_ref field');
  rejects('wrong snapshot pointer type', s => { s.source.input_ref = {}; }, 'invalid source input_ref');
  rejects('wrong snapshot path', s => { s.source.input_ref = 'artifacts/audit-log.md#input'; }, 'invalid source input_ref');
  rejects('snapshot source identity drift', (s, f) => mutateSnapshot(f, r => { r.source.identity = 'other-source'; }), 'snapshot source mismatch');
  rejects('snapshot version drift', (s, f) => mutateSnapshot(f, r => { r.source.version = 2; }), 'snapshot source mismatch');
  rejects('snapshot body changed', (s, f) => mutateSnapshot(f, r => { r.original_text += 'changed'; }), 'source content hash mismatch');
  rejects('snapshot final newline removed', (s, f) => mutateSnapshot(f, r => { r.original_text = r.original_text.trimEnd(); }), 'source content hash mismatch');
  rejects('snapshot clarification added', (s, f) => mutateSnapshot(f, r => { r.clarifications = [{ identity: 'C-1', text: 'Confirmed clarification' }]; }), 'source content hash mismatch');
  rejects('duplicate clarification identity', (s, f) => mutateSnapshot(f, r => { r.clarifications = [{ identity: 'C-1', text: 'a' }, { identity: 'C-1', text: 'b' }]; }), 'invalid workflow input snapshot');
  rejects('invalid clarification container', (s, f) => mutateSnapshot(f, r => { r.clarifications = {}; }), 'invalid workflow input snapshot');
  rejects('empty original input', (s, f) => mutateSnapshot(f, r => { r.original_text = ''; }), 'invalid workflow input snapshot');
  rejects('missing snapshot anchor', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('<a id="input-fixture"></a>', ''); }, 'input snapshot anchor');
  rejects('duplicate snapshot block', (s, f) => { f[artifactFiles[0]] += snapshotBlock.split('<a id="input-fixture"></a>')[1]; }, 'ambiguous workflow-input block');
  rejects('malformed snapshot JSON', (s, f) => { f[artifactFiles[0]] = f[artifactFiles[0]].replace('```workflow-input\n{', '```workflow-input\n!{'); }, 'invalid input snapshot JSON');
  rejects('unconfirmed source cannot hide mismatched snapshot', (s, f) => {
    s.source.confirmed = false; mutateSnapshot(f, r => { r.original_text += 'drift'; });
  }, 'source content hash mismatch');
  const exact = { format: 'workflow-input-v1', source: { type: 'user_text', identity: 'fixture', version: null }, original_text: 'Исходный текст \r\n\n```\n<!-- -->\n', clarifications: [{ identity: 'C-1', text: 'Уточнение  \n' }] };
  const roundTrip = JSON.parse(JSON.stringify(exact));
  assert.equal(composeInput(roundTrip), exact.original_text + '\n\nУточнение C-1:\nУточнение  \n'); count++;
  assert.equal(inputHash('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'); count++;
  assert.notEqual(inputHash('x\r\n'), inputHash('x\n')); count++;
  const previous = readInputSnapshot(source.input_ref, p => files[p]);
  const newVersionFiles = { ...files };
  mutateSnapshot(newVersionFiles, r => { r.source.version = 2; });
  const versionOnly = compareInputs(previous, readInputSnapshot(source.input_ref, p => newVersionFiles[p]));
  assert.equal(versionOnly.version_changed, true); assert.equal(versionOnly.content_changed, false); count++;
  mutateSnapshot(newVersionFiles, r => { r.clarifications = [{ identity: 'C-1', text: 'New clarification' }]; });
  const changed = compareInputs(previous, readInputSnapshot(source.input_ref, p => newVersionFiles[p]));
  assert.equal(changed.clarifications_changed, true); assert.equal(changed.content_changed, true); count++;
  console.log(`PASS: ${count} validator regression checks`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--self-test')) selfTest();
  else {
    const root = fileURLToPath(new URL('../..', import.meta.url));
    try {
      const state = JSON.parse(fs.readFileSync(path.join(root, 'artifacts/workflow-state.json'), 'utf8'));
      const read = file => {
        const p = path.join(root, file);
        return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
      };
      const errors = validateWorkflow(state, read);
      if (process.argv.includes('--compare-input')) {
        const ref = process.argv[process.argv.indexOf('--compare-input') + 1];
        console.log(JSON.stringify(compareInputs(readInputSnapshot(ref, read), readInputSnapshot(state.source?.input_ref, read)), null, 2));
      }
      if (process.argv.includes('--source-hash')) {
        const argument = process.argv[process.argv.indexOf('--source-hash') + 1];
        const ref = argument && !argument.startsWith('--') ? argument : state.source?.input_ref;
        const input = readInputSnapshot(ref, read);
        console.log(`Computed source SHA-256 (${ref}): ${input.sha256}`);
      }
      if (errors.length) { console.error(errors.map(e => `ERROR: ${e}`).join('\n')); process.exitCode = 1; }
      else console.log('PASS: structural state/artifact consistency; this does not grant a Quality Gate PASS');
    } catch (error) { console.error(`ERROR: cannot validate workflow (${error.code ?? error.name})`); process.exitCode = 1; }
  }
}
