const fs = require('fs');
const path = require('path');

const REQUIRED_BASE_FIELDS = ['id', 'platform', 'repo_url'];
const REQUIRED_PLATFORM_FIELDS = {
  railway: ['project_id', 'service_id'],
  vercel: ['project_id']
};
const REQUIRED_SECRETS = ['RAILWAY_TOKEN', 'VERCEL_TOKEN'];
const GITHUB_REPO_URL = /^https:\/\/github\.com\/[^/]+\/[^/]+\/?$/;

function readRegistry(registryPath = path.join(__dirname, '..', 'registry', 'repos.json')) {
  return JSON.parse(fs.readFileSync(registryPath, 'utf8'));
}

function validateRegistry(registry) {
  const errors = [];
  const repos = Array.isArray(registry?.repos) ? registry.repos : [];

  if (repos.length === 0) {
    errors.push('registry/repos.json must contain at least one repository entry.');
    return errors;
  }

  for (const repo of repos) {
    const repoLabel = repo?.id || '<unknown>';

    for (const field of REQUIRED_BASE_FIELDS) {
      if (!repo?.[field] || typeof repo[field] !== 'string') {
        errors.push(`Registry entry '${repoLabel}' is missing '${field}'.`);
      }
    }

    if (typeof repo?.platform === 'string' && !REQUIRED_PLATFORM_FIELDS[repo.platform]) {
      errors.push(`Registry entry '${repoLabel}' has unsupported platform '${repo?.platform}'.`);
      continue;
    }

    if (typeof repo?.repo_url === 'string' && !GITHUB_REPO_URL.test(repo.repo_url)) {
      errors.push(`Registry entry '${repoLabel}' has an invalid repo_url.`);
    }

    for (const field of REQUIRED_PLATFORM_FIELDS[repo.platform]) {
      if (!repo[field] || typeof repo[field] !== 'string') {
        errors.push(`Registry entry '${repoLabel}' is missing '${field}'.`);
      }
    }

    for (const [field, value] of Object.entries(repo)) {
      if (typeof value === 'string' && value.includes('replace-with-')) {
        errors.push(`Registry entry '${repoLabel}' contains unresolved placeholder '${field}'.`);
      }
    }
  }

  return errors;
}

function validateSecrets(env = process.env) {
  return REQUIRED_SECRETS
    .filter((name) => env[name] == null || env[name].trim() === '')
    .map((name) => `Missing required GitHub secret '${name}'.`);
}

function runChecks() {
  const registryErrors = validateRegistry(readRegistry());
  const secretErrors = validateSecrets();
  const errors = [...registryErrors, ...secretErrors];

  if (errors.length > 0) {
    console.error('Bootstrap validation failed:');
    for (const error of errors) {
      console.error(`- ${error}`);
    }
    process.exit(1);
  }

  console.log('✅ Autokey system: registry deployment keys are valid.');
  console.log('✅ Auto secret system: required GitHub deploy secrets are available.');
}

if (require.main === module) {
  runChecks();
}

module.exports = {
  REQUIRED_SECRETS,
  readRegistry,
  runChecks,
  validateRegistry,
  validateSecrets
};
