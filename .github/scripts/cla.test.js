// Tests of cla.js, without network: `node --test .github/scripts/`.
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const cla = require('./cla.js');

const ROOT = path.join(__dirname, '..', '..');
const CLA_TEXT = 'Contributor License Agreement, test text.\n';

const users = {
  maintainer: { login: 'Robvred', id: 1 },
  dependabot: { login: 'dependabot[bot]', id: 49699333 },
  alice: { login: 'alice', id: 101 },
  bob: { login: 'bob', id: 102 },
};

function httpError(status) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

// In-memory stand-in for the parts of Octokit the module uses.
function fakeGitHub({ branch = true, signatures = null, commits = [], opener = users.alice, conflicts = 0 } = {}) {
  const state = {
    file: signatures === null ? null : { document: { version: 1, signatures }, sha: 'blob-0' },
    comments: [],
    statuses: [],
    writes: [],
    conflictsLeft: conflicts,
    nextComment: 1000,
  };
  const encode = (document) => Buffer.from(JSON.stringify(document)).toString('base64');
  const github = {
    paginate: async (method, params) => method(params).then((r) => r.data),
    rest: {
      pulls: {
        get: async () => ({ data: { number: 7, head: { sha: 'head-sha' }, user: opener } }),
        listCommits: async () => ({ data: commits }),
      },
      repos: {
        getBranch: async () => {
          if (!branch) throw httpError(404);
          return { data: { name: cla.BRANCH } };
        },
        getContent: async ({ path: p, ref }) => {
          assert.equal(p, cla.SIGNATURES_PATH);
          assert.equal(ref, cla.BRANCH);
          if (!state.file) throw httpError(404);
          return { data: { type: 'file', sha: state.file.sha, content: encode(state.file.document) } };
        },
        createOrUpdateFileContents: async (params) => {
          state.writes.push(params);
          if (state.conflictsLeft > 0) {
            // Another run wrote first: the file changed under us.
            state.conflictsLeft -= 1;
            const other = { login: 'carol', id: 103, pull_request: 8 };
            const previous = state.file ? state.file.document.signatures : [];
            state.file = { document: { version: 1, signatures: [...previous, other] }, sha: `blob-${state.writes.length}` };
            throw httpError(409);
          }
          if ((state.file && params.sha !== state.file.sha) || (!state.file && params.sha)) throw httpError(409);
          const document = JSON.parse(Buffer.from(params.content, 'base64').toString('utf8'));
          state.file = { document, sha: `blob-${state.writes.length}` };
          return { data: {} };
        },
        createCommitStatus: async (params) => {
          state.statuses.push(params);
          return { data: {} };
        },
      },
      issues: {
        listComments: async () => ({ data: state.comments }),
        createComment: async ({ body }) => {
          state.comments.push({ id: state.nextComment++, user: { login: 'github-actions[bot]' }, body });
          return { data: {} };
        },
        updateComment: async ({ comment_id: id, body }) => {
          state.comments.find((c) => c.id === id).body = body;
          return { data: {} };
        },
      },
    },
  };
  return { github, state };
}

function fakeCore() {
  return { failed: null, info: () => {}, setFailed(message) { this.failed = message; } };
}

const repoPayload = { default_branch: 'main' };

function prContext() {
  return {
    eventName: 'pull_request_target',
    repo: { owner: 'HouseCairn', repo: 'HouseCairn' },
    payload: { pull_request: { number: 7 }, repository: repoPayload },
  };
}

function commentContext(user, body) {
  return {
    eventName: 'issue_comment',
    repo: { owner: 'HouseCairn', repo: 'HouseCairn' },
    payload: {
      issue: { number: 7, pull_request: {} },
      comment: { id: 555, user, body, created_at: '2026-11-07T12:00:00Z' },
      repository: repoPayload,
    },
  };
}

const commitBy = (user, sha = `sha-${user.login}`) => ({ sha, author: user });

test('the maintainer and bots are exempt', async () => {
  const { github, state } = fakeGitHub({
    signatures: [],
    commits: [commitBy(users.dependabot)],
    opener: users.dependabot,
  });
  const result = await cla.run({ github, context: prContext(), core: fakeCore() });
  assert.equal(result.ok, true);
  assert.equal(state.statuses.at(-1).state, 'success');
  assert.equal(state.statuses.at(-1).context, 'CLA');
  assert.equal(state.statuses.at(-1).sha, 'head-sha');
  assert.equal(state.comments.length, 0, 'no comment when nothing is missing');
  assert.equal(cla.isExempt('robvred'), true, 'logins compare case-insensitively');
  assert.equal(cla.isExempt('alice'), false);
});

test('an unsigned author fails the check and gets one comment, updated not repeated', async () => {
  const { github, state } = fakeGitHub({ signatures: [], commits: [commitBy(users.alice)] });
  const core = fakeCore();
  await cla.run({ github, context: prContext(), core });
  await cla.run({ github, context: prContext(), core });
  assert.equal(state.statuses.at(-1).state, 'failure');
  assert.equal(state.comments.length, 1);
  assert.match(state.comments[0].body, /@alice/);
  assert.ok(state.comments[0].body.includes(`\`\`\`text\n${cla.PHRASE}\n\`\`\``));
  assert.equal(core.failed, null, 'missing signatures fail the status, not the job');
});

test('the exact phrase signs its author and records the signature', async () => {
  const { github, state } = fakeGitHub({ signatures: null, commits: [commitBy(users.alice)] });
  await cla.run({ github, context: prContext(), core: fakeCore() });
  const result = await cla.run(
    { github, context: commentContext(users.alice, `  ${cla.PHRASE}\n`), core: fakeCore() },
    { claText: CLA_TEXT },
  );
  assert.equal(result.ok, true);
  assert.equal(state.statuses.at(-1).state, 'success');
  assert.deepEqual(state.file.document.signatures, [
    {
      login: 'alice',
      id: 101,
      pull_request: 7,
      comment_id: 555,
      signed_at: '2026-11-07T12:00:00Z',
      cla_sha256: cla.sha256(CLA_TEXT),
    },
  ]);
  assert.equal(state.writes[0].branch, cla.BRANCH);
  assert.equal(state.writes[0].sha, undefined, 'first signature creates the file');
  assert.match(state.comments[0].body, /All authors have signed/);
});

test('a nearly exact comment does not sign', async () => {
  const near = [
    `${cla.PHRASE}.`,
    cla.PHRASE.toLowerCase(),
    `I agree. ${cla.PHRASE}`,
    `> ${cla.PHRASE}`,
    cla.PHRASE.replace('the CLA Document', 'the CLA document'),
  ];
  for (const body of near) {
    assert.equal(cla.isSignature(body), false, body);
    const { github, state } = fakeGitHub({ signatures: [], commits: [commitBy(users.alice)] });
    const result = await cla.run({ github, context: commentContext(users.alice, body), core: fakeCore() });
    assert.equal(result, undefined, 'the comment is ignored');
    assert.equal(state.writes.length, 0);
    assert.equal(state.statuses.length, 0);
  }
});

test("a third party's comment signs only that third party", async () => {
  const { github, state } = fakeGitHub({ signatures: [], commits: [commitBy(users.alice)] });
  const result = await cla.run(
    { github, context: commentContext(users.bob, cla.PHRASE), core: fakeCore() },
    { claText: CLA_TEXT },
  );
  assert.deepEqual(state.file.document.signatures.map((s) => s.login), ['bob']);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing.map((s) => s.login), ['alice']);
  assert.equal(state.statuses.at(-1).state, 'failure');
});

test('a write conflict is retried on the new version of the file', async () => {
  const { github, state } = fakeGitHub({
    signatures: [{ login: 'dave', id: 104 }],
    commits: [commitBy(users.alice)],
    conflicts: 1,
  });
  const result = await cla.run(
    { github, context: commentContext(users.alice, cla.PHRASE), core: fakeCore() },
    { claText: CLA_TEXT },
  );
  assert.equal(result.ok, true);
  assert.equal(state.writes.length, 2);
  assert.equal(state.writes[0].sha, 'blob-0');
  assert.equal(state.writes[1].sha, 'blob-1', 'second write names the blob written by the other run');
  assert.deepEqual(state.file.document.signatures.map((s) => s.login), ['dave', 'carol', 'alice']);
});

test('a signature already recorded is not written again', async () => {
  const { github, state } = fakeGitHub({ signatures: [{ login: 'old-name', id: 101 }], commits: [commitBy(users.alice)] });
  const result = await cla.run(
    { github, context: commentContext(users.alice, cla.PHRASE), core: fakeCore() },
    { claText: CLA_TEXT },
  );
  assert.equal(result.ok, true, 'matched by account id, which survives a renaming');
  assert.equal(state.writes.length, 0);
});

test('a commit without a GitHub account fails the check with an explanation', async () => {
  const { github, state } = fakeGitHub({
    signatures: [{ login: 'alice', id: 101 }],
    commits: [commitBy(users.alice), { sha: 'abcdef1234567890', author: null }],
  });
  const result = await cla.run({ github, context: prContext(), core: fakeCore() });
  assert.equal(result.ok, false);
  assert.deepEqual(result.unlinked, ['abcdef1234567890']);
  assert.equal(state.statuses.at(-1).state, 'failure');
  assert.match(state.statuses.at(-1).description, /without a GitHub account/);
  assert.match(state.comments[0].body, /not linked to a GitHub account.*`abcdef123456`/s);
});

test('the person who opened the pull request must sign too', async () => {
  const { github } = fakeGitHub({ signatures: [], commits: [commitBy(users.maintainer)], opener: users.bob });
  const result = await cla.run({ github, context: prContext(), core: fakeCore() });
  assert.deepEqual(result.missing.map((s) => s.login), ['bob']);
});

test('a missing signatures branch fails the job with a clear message', async () => {
  const { github, state } = fakeGitHub({ branch: false, commits: [commitBy(users.alice)] });
  const core = fakeCore();
  await cla.run({ github, context: prContext(), core });
  assert.match(core.failed, /"cla-signatures" branch does not exist/);
  assert.equal(state.statuses.at(-1).state, 'failure');
  assert.equal(state.writes.length, 0);
});

test('other comments and events are ignored', async () => {
  const { github, state } = fakeGitHub({ signatures: [] });
  assert.equal(await cla.run({ github, context: commentContext(users.alice, 'LGTM'), core: fakeCore() }), undefined);
  const issue = commentContext(users.alice, cla.PHRASE);
  delete issue.payload.issue.pull_request;
  assert.equal(await cla.run({ github, context: issue, core: fakeCore() }), undefined);
  assert.equal(state.statuses.length + state.writes.length, 0);
  assert.equal(cla.isRecheck(' Recheck '), true);
});

test('CONTRIBUTING.md and the workflow quote the same phrase', () => {
  const contributing = fs.readFileSync(path.join(ROOT, 'CONTRIBUTING.md'), 'utf8');
  assert.ok(contributing.includes(`\`\`\`text\n   ${cla.PHRASE}\n   \`\`\``), 'CONTRIBUTING.md');
  const workflow = fs.readFileSync(path.join(ROOT, '.github', 'workflows', 'cla.yml'), 'utf8');
  assert.ok(workflow.includes(cla.PHRASE), 'cla.yml');
  assert.ok(fs.existsSync(path.join(ROOT, 'CLA.md')), 'CLA.md is the signed document');
});
