// Contributor License Agreement check, run by .github/workflows/cla.yml through
// actions/github-script (docs/adr/0014).
//
// This module is loaded from the default branch, never from the pull request.
// It only reads metadata through the GitHub API (the pull request, its commits,
// one comment) and writes three things: the signatures file on the
// `cla-signatures` branch, one bot comment on the pull request, and the `CLA`
// commit status on its head.
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');

// The exact comment a contributor posts to sign, also quoted in CONTRIBUTING.md.
const PHRASE = 'I have read the CLA Document and I hereby sign the CLA';
const RECHECK = 'recheck';
// Accounts that never sign: the maintainer and GitHub's bots. Logins are
// compared case-insensitively, as GitHub does.
const EXEMPT = ['Robvred', 'dependabot[bot]', 'github-actions[bot]'];
const BRANCH = 'cla-signatures';
const SIGNATURES_PATH = 'signatures/v1/cla.json';
const STATUS_CONTEXT = 'CLA';
const MARKER = '<!-- housecairn-cla -->';
const BOT_LOGIN = 'github-actions[bot]';
const MAX_ATTEMPTS = 5;

const exempt = new Set(EXEMPT.map((login) => login.toLowerCase()));

function isExempt(login) {
  return typeof login === 'string' && exempt.has(login.toLowerCase());
}

// A signature is a comment whose whole body, without leading and trailing
// white space, is the phrase. Nothing else, not even the phrase in a sentence.
function isSignature(body) {
  return typeof body === 'string' && body.trim() === PHRASE;
}

function isRecheck(body) {
  return typeof body === 'string' && body.trim().toLowerCase() === RECHECK;
}

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

// The accounts that must have signed: the GitHub account of the author of
// every commit, and the person who opened the pull request (a commit author
// address can be anyone's, the opener cannot). Commits whose author address
// is not linked to a GitHub account cannot be signed for and are returned
// apart.
function requiredSigners(commits, opener) {
  const signers = new Map();
  const unlinked = [];
  const add = (user) => {
    if (!signers.has(user.id)) signers.set(user.id, { login: user.login, id: user.id });
  };
  for (const commit of commits) {
    if (commit.author && Number.isInteger(commit.author.id) && commit.author.login) {
      add(commit.author);
    } else {
      unlinked.push(commit.sha);
    }
  }
  if (opener && Number.isInteger(opener.id)) add(opener);
  return { signers: [...signers.values()], unlinked };
}

// Signatures are matched by numeric account id, which survives a renaming.
function evaluate({ signers, unlinked }, document) {
  const signed = new Set(document.signatures.map((s) => s.id));
  const missing = signers.filter((s) => !isExempt(s.login) && !signed.has(s.id));
  return { ok: missing.length === 0 && unlinked.length === 0, missing, unlinked };
}

function emptyDocument() {
  return { version: 1, signatures: [] };
}

function parseDocument(content) {
  const document = JSON.parse(Buffer.from(content, 'base64').toString('utf8'));
  if (!document || !Array.isArray(document.signatures)) {
    throw new Error(`${SIGNATURES_PATH} on ${BRANCH} has no "signatures" list.`);
  }
  return document;
}

function statusOf(error) {
  return error && typeof error.status === 'number' ? error.status : undefined;
}

async function ensureBranch(github, repo) {
  try {
    await github.rest.repos.getBranch({ ...repo, branch: BRANCH });
  } catch (error) {
    if (statusOf(error) === 404) {
      throw new Error(
        `The "${BRANCH}" branch does not exist, so signatures cannot be read or ` +
          'recorded. A maintainer must create it (outside the main ruleset) before ' +
          'this check can pass; see docs/adr/0014.',
      );
    }
    throw error;
  }
}

// Reads the signatures file; a missing file is an empty list (sha undefined).
async function readSignatures(github, repo) {
  try {
    const { data } = await github.rest.repos.getContent({
      ...repo,
      path: SIGNATURES_PATH,
      ref: BRANCH,
    });
    if (Array.isArray(data) || data.type !== 'file' || typeof data.content !== 'string') {
      throw new Error(`${SIGNATURES_PATH} on ${BRANCH} is not a readable file.`);
    }
    return { document: parseDocument(data.content), sha: data.sha };
  } catch (error) {
    if (statusOf(error) === 404) return { document: emptyDocument(), sha: undefined };
    throw error;
  }
}

// Adds one signature with optimistic concurrency: the write names the blob it
// replaces (`sha`); if another run changed the file in between, GitHub refuses
// it (409, or 422 when the file appeared meanwhile) and the file is read again.
async function recordSignature(github, repo, entry) {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    const { document, sha } = await readSignatures(github, repo);
    if (document.signatures.some((s) => s.id === entry.id)) {
      return { document, recorded: false };
    }
    document.signatures.push(entry);
    const content = Buffer.from(`${JSON.stringify(document, null, 2)}\n`).toString('base64');
    try {
      await github.rest.repos.createOrUpdateFileContents({
        ...repo,
        path: SIGNATURES_PATH,
        branch: BRANCH,
        message: `chore(cla): record the signature of @${entry.login} (#${entry.pull_request})`,
        content,
        ...(sha ? { sha } : {}),
      });
      return { document, recorded: true };
    } catch (error) {
      const status = statusOf(error);
      if ((status === 409 || status === 422) && attempt < MAX_ATTEMPTS) continue;
      throw error;
    }
  }
  throw new Error('unreachable');
}

function commentBody(result, links) {
  if (result.ok) {
    return `${MARKER}\n**Contributor License Agreement**\n\nAll authors have signed the CLA. Thank you.\n`;
  }
  const lines = [
    MARKER,
    '**Contributor License Agreement**',
    '',
    'Thank you for your pull request. Before it can be merged, the author of every ' +
      `commit and the person who opened it must sign the [Contributor License Agreement](${links.cla}) ` +
      'once. They keep the copyright of their work.',
  ];
  if (result.missing.length > 0) {
    lines.push(
      '',
      `Not signed yet: ${result.missing.map((s) => `@${s.login}`).join(', ')}.`,
      '',
      'To sign, read the CLA, then post this comment on this pull request, exactly as written:',
      '',
      '```text',
      PHRASE,
      '```',
    );
  }
  if (result.unlinked.length > 0) {
    lines.push(
      '',
      'These commits are not linked to a GitHub account, so their author cannot sign: ' +
        `${result.unlinked.map((sha) => `\`${sha.slice(0, 12)}\``).join(', ')}. ` +
        'Use an email address of your GitHub account (or its noreply address) as the ' +
        'commit author, then amend the commits and force-push the branch.',
    );
  }
  lines.push('', `Comment \`${RECHECK}\` to run the check again. See [CONTRIBUTING.md](${links.contributing}).`);
  return `${lines.join('\n')}\n`;
}

// One bot comment per pull request, updated rather than repeated. When every
// author has signed and there is no comment yet, none is created.
async function upsertComment(github, repo, number, result, links) {
  const comments = await github.paginate(github.rest.issues.listComments, {
    ...repo,
    issue_number: number,
    per_page: 100,
  });
  const mine = comments.find(
    (c) => c.user && c.user.login === BOT_LOGIN && typeof c.body === 'string' && c.body.startsWith(MARKER),
  );
  const body = commentBody(result, links);
  if (mine) {
    if (mine.body !== body) {
      await github.rest.issues.updateComment({ ...repo, comment_id: mine.id, body });
    }
  } else if (!result.ok) {
    await github.rest.issues.createComment({ ...repo, issue_number: number, body });
  }
}

function describe(result) {
  if (result.ok) return 'All authors have signed the CLA.';
  const parts = [];
  if (result.missing.length > 0) parts.push(`Not signed: ${result.missing.map((s) => s.login).join(', ')}`);
  if (result.unlinked.length > 0) parts.push(`${result.unlinked.length} commit(s) without a GitHub account`);
  const text = `${parts.join('; ')}.`;
  return text.length <= 140 ? text : `${text.slice(0, 137)}...`;
}

async function setStatus(github, repo, sha, state, description, url) {
  await github.rest.repos.createCommitStatus({
    ...repo,
    sha,
    state,
    context: STATUS_CONTEXT,
    description,
    target_url: url,
  });
}

function pullRequestNumber(context) {
  if (context.eventName === 'pull_request_target') return context.payload.pull_request.number;
  if (context.eventName === 'issue_comment' && context.payload.issue && context.payload.issue.pull_request) {
    return context.payload.issue.number;
  }
  return undefined;
}

async function run({ github, context, core }, options = {}) {
  const repo = { owner: context.repo.owner, repo: context.repo.repo };
  const number = pullRequestNumber(context);
  if (number === undefined) {
    core.info('Not a pull request event: nothing to check.');
    return undefined;
  }
  const comment = context.eventName === 'issue_comment' ? context.payload.comment : undefined;
  if (comment && !isSignature(comment.body) && !isRecheck(comment.body)) {
    core.info('The comment is neither the signature phrase nor "recheck": nothing to do.');
    return undefined;
  }

  const base = `https://github.com/${repo.owner}/${repo.repo}/blob/${context.payload.repository.default_branch}`;
  const links = {
    cla: `${base}/CLA.md`,
    contributing: `${base}/CONTRIBUTING.md#before-your-pull-request-can-be-merged`,
  };
  const { data: pull } = await github.rest.pulls.get({ ...repo, pull_number: number });
  const head = pull.head.sha;

  try {
    await ensureBranch(github, repo);
    let document;
    if (comment && isSignature(comment.body)) {
      const claText = options.claText ?? fs.readFileSync(options.claPath ?? 'CLA.md', 'utf8');
      const entry = {
        login: comment.user.login,
        id: comment.user.id,
        pull_request: number,
        comment_id: comment.id,
        signed_at: comment.created_at,
        cla_sha256: sha256(claText),
      };
      const outcome = await recordSignature(github, repo, entry);
      document = outcome.document;
      core.info(
        outcome.recorded
          ? `Recorded the signature of @${entry.login}.`
          : `@${entry.login} had already signed.`,
      );
    } else {
      ({ document } = await readSignatures(github, repo));
    }

    const commits = await github.paginate(github.rest.pulls.listCommits, {
      ...repo,
      pull_number: number,
      per_page: 100,
    });
    const result = evaluate(requiredSigners(commits, pull.user), document);
    await setStatus(github, repo, head, result.ok ? 'success' : 'failure', describe(result), links.contributing);
    await upsertComment(github, repo, number, result, links);
    core.info(describe(result));
    return result;
  } catch (error) {
    await setStatus(
      github,
      repo,
      head,
      'failure',
      'The CLA check could not run; see the CLA workflow log.',
      links.contributing,
    );
    core.setFailed(error.message);
    return undefined;
  }
}

module.exports = {
  BRANCH,
  EXEMPT,
  MARKER,
  PHRASE,
  SIGNATURES_PATH,
  STATUS_CONTEXT,
  commentBody,
  evaluate,
  isExempt,
  isRecheck,
  isSignature,
  recordSignature,
  requiredSigners,
  run,
  sha256,
};
