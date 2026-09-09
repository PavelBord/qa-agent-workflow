import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const artifactFiles = ['artifacts/requirement-review.md', 'artifacts/jira-tasks.md', 'artifacts/qase-test-model.md'];
const artifactKeys = ['requirement_review', 'jira_tasks', 'qase_model'];
const statuses = ['NOT_RUN', 'PASS', 'FAIL', 'BLOCKED'];
const sourceKey = source => JSON.stringify([source?.type, source?.identity, source?.version ?? null, source?.content_sha256 ?? null]);
const nonempty = value => typeof value === 'string' && value.trim().length > 0;

export function validateWorkflow(state, read) {
  const errors = [];
  const check = (ok, message) => { if (!ok) errors.push(message); };
  if (!state || typeof state !== 'object') return ['state must be an object'];
  check(state.schema_version === 1, 'unsupported schema_version');
  check(nonempty(state.run_id), 'missing run_id');
  const source = state.source;
  check(['Confluence', 'user_text'].includes(source?.type), 'unsupported source type');
  check(nonempty(source?.identity), 'missing source identity');
  check(source?.version == null || (Number.isInteger(source.version) && source.version > 0) || nonempty(source?.version), 'invalid source version');
  check(source?.content_sha256 == null || /^[a-f0-9]{64}$/.test(source.content_sha256), 'invalid content hash');
  check(typeof source?.confirmed === 'boolean', 'missing source confirmation state');
  const gates = [1, 2, 3].map(i => state.gates?.[`gate_${i}`]);
  gates.forEach((g, i) => check(statuses.includes(g), `invalid gate_${i + 1}`));
  gates.forEach((g, i) => {
    if (g === 'PASS') check(gates.slice(0, i).every(x => x === 'PASS'), `gate_${i + 1} PASS requires preceding PASS`);
  });
  const findings = state.blocking_findings;
  check(Array.isArray(findings) && findings.every(nonempty), 'invalid blocking_findings');
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
    check(source?.confirmed === true && nonempty(source?.confirmed_at) && Number.isFinite(Date.parse(source.confirmed_at)) && /^[a-f0-9]{64}$/.test(source?.content_sha256 ?? ''), 'progress/PASS requires confirmed source and content hash');
  }
  const active = state.active_artifacts;
  check(active && typeof active === 'object' && artifactKeys.every(k => Object.hasOwn(active, k)), 'missing active artifact slots');
  artifactKeys.forEach((key, i) => {
    const pointer = active?.[key];
    const required = gates[i] !== 'NOT_RUN' || state.next_stage === `gate_${i + 1}`;
    if (pointer == null) { check(!required, `missing active artifact: ${key}`); return; }
    if (typeof pointer !== 'string') { errors.push(`invalid pointer: ${key}`); return; }
    const [file, anchor, extra] = pointer.split('#');
    if (file !== artifactFiles[i] || !/^[a-z0-9-]+$/.test(anchor ?? '') || extra !== undefined) {
      errors.push(`invalid pointer: ${key}`); return;
    }
    const content = read(file);
    if (typeof content !== 'string') { errors.push(`missing artifact: ${key}`); return; }
    const marker = `<a id="${anchor}"></a>`;
    const parts = content.split(marker);
    if (parts.length !== 2) { errors.push(`missing or ambiguous active section: ${key}`); return; }
    const section = parts[1].split(/\n## /)[0];
    const metadata = [...section.matchAll(/<!-- workflow-review\s+([^\n]+?)\s*-->/g)];
    if (metadata.length !== 1) { errors.push(`missing or ambiguous review metadata: ${key}`); return; }
    let review;
    try { review = JSON.parse(metadata[0][1]); } catch { errors.push(`invalid review JSON: ${key}`); return; }
    if (!review || typeof review !== 'object' || Array.isArray(review)) { errors.push(`invalid review object: ${key}`); return; }
    check(review.run_id === state.run_id, `run_id mismatch: ${key}`);
    check(sourceKey(review.source) === sourceKey(source), `source mismatch: ${key}`);
    check(review.gate === `gate_${i + 1}` && review.status === gates[i], `gate mismatch: ${key}`);
    check(nonempty(review.reason), `missing review reason: ${key}`);
    if (gates[i] !== 'NOT_RUN') check(review.decision_by === 'qa-orchestrator', `missing orchestrator decision: ${key}`);
    const labels = [...section.matchAll(new RegExp(`Текущий Gate #${i + 1}:\\s*(NOT_RUN|PASS|FAIL|BLOCKED)`, 'g'))];
    check(labels.length === 1 && labels[0][1] === gates[i], `current gate label mismatch: ${key}`);
  });
  const audit = read('artifacts/audit-log.md');
  check(typeof audit === 'string' && audit.split('\n').some(line => line.startsWith('| ') && line.split('|')[1]?.trim() === state.run_id), 'missing audit row for current run');
  return errors;
}

function selfTest() {
  const source = { type: 'user_text', identity: 'user supplied requirements', version: null, content_sha256: 'a'.repeat(64), confirmed: true, confirmed_at: '2026-09-09T07:00:00Z' };
  const base = { schema_version: 1, run_id: 'test-run', source, gates: { gate_1: 'PASS', gate_2: 'PASS', gate_3: 'PASS' }, next_stage: 'completed', active_artifacts: {}, blocking_findings: [] };
  const files = { 'artifacts/audit-log.md': '| test-run | time | verified |' };
  artifactKeys.forEach((key, i) => {
    base.active_artifacts[key] = `${artifactFiles[i]}#current`;
    files[artifactFiles[i]] = `<a id="current"></a>\n<!-- workflow-review ${JSON.stringify({ run_id: base.run_id, source, gate: `gate_${i + 1}`, status: 'PASS', decision_by: 'qa-orchestrator', reason: 'fixture review' })} -->\nТекущий Gate #${i + 1}: PASS\n`;
  });
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
  test('first launch without downstream artifacts', (s, f) => { s.next_stage = 'requirements_review'; artifactKeys.forEach((k, i) => { s.gates[`gate_${i+1}`] = 'NOT_RUN'; s.active_artifacts[k] = null; delete f[artifactFiles[i]]; }); }, true);
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
    s.source.confirmed = false; s.source.content_sha256 = null; s.source.confirmed_at = null;
    s.next_stage = 'requirements_clarification'; s.blocking_findings = ['AMB-1'];
    artifactKeys.forEach((key, i) => {
      s.gates[`gate_${i+1}`] = 'BLOCKED';
      const review = { run_id: s.run_id, source: s.source, gate: `gate_${i+1}`, status: 'BLOCKED', decision_by: 'qa-orchestrator', reason: 'pending clarification' };
      f[artifactFiles[i]] = `<a id="current"></a>\n<!-- workflow-review ${JSON.stringify(review)} -->\nТекущий Gate #${i+1}: BLOCKED`;
    });
  }, true);
  console.log(`PASS: ${count} validator regression checks`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--self-test')) selfTest();
  else {
    const root = fileURLToPath(new URL('../..', import.meta.url));
    try {
      const state = JSON.parse(fs.readFileSync(path.join(root, 'artifacts/workflow-state.json'), 'utf8'));
      const errors = validateWorkflow(state, file => {
        const p = path.join(root, file);
        return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
      });
      if (errors.length) { console.error(errors.map(e => `ERROR: ${e}`).join('\n')); process.exitCode = 1; }
      else console.log('PASS: structural state/artifact consistency; this does not grant a Quality Gate PASS');
    } catch (error) { console.error(`ERROR: cannot validate workflow (${error.code ?? error.name})`); process.exitCode = 1; }
  }
}
