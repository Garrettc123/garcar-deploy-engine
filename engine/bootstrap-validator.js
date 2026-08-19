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

function containsPlaceholder(value) {
  if (typeof value === 'string') {
    return value.includes('replace-with-');
  }

  if (Array.isArray(value)) {
    return value.some(containsPlaceholder);
  }

  if (value && typeof value === 'object') {
    return Object.values(value).some(containsPlaceholder);
  }

  return false;
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
      const fieldValue = repo?.[field];
      if (fieldValue == null || typeof fieldValue !== 'string' || fieldValue.trim() === '') {
        errors.push(`Registry entry '${repoLabel}' is missing '${field}'.`);
      }
    }

    const platform = typeof repo?.platform === 'string' ? repo.platform : '';
    const requiredPlatformFields = REQUIRED_PLATFORM_FIELDS[platform];

    if (platform && !requiredPlatformFields) {
      errors.push(`Registry entry '${repoLabel}' has unsupported platform '${repo?.platform}'.`);
    }

    if (typeof repo?.repo_url === 'string' && !GITHUB_REPO_URL.test(repo.repo_url)) {
      errors.push(`Registry entry '${repoLabel}' has an invalid repo_url.`);
    }

    if (requiredPlatformFields) {
      for (const field of requiredPlatformFields) {
        const fieldValue = repo?.[field];
        if (fieldValue == null || typeof fieldValue !== 'string' || fieldValue.trim() === '') {
          errors.push(`Registry entry '${repoLabel}' is missing '${field}'.`);
        }
      }
    }

    for (const [field, value] of Object.entries(repo || {})) {
      if (containsPlaceholder(value)) {
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
  let registryErrors;

  try {
    registryErrors = validateRegistry(readRegistry());
  } catch (error) {
    registryErrors = [`Unable to read registry/repos.json: ${error.message}`];
  }

  const secretErrors = validateSecrets();
  const errors = [...registryErrors, ...secretErrors];

  if (errors.length > 0) {
    console.error('Bootstrap validation failed:');
    for (const error of errors) {
      console.error(`- ${error}`);
    }
    process.exit(1);
  }

  if (registryErrors.length === 0) {
    console.log('✅ Autokey system complete: registry deployment keys are valid.');
  }

  if (secretErrors.length === 0) {
    console.log('✅ Auto secret system complete: required GitHub deploy secrets are available.');
  }
}

if (require.main === module) {
  runChecks();
}

module.exports = {
  REQUIRED_SECRETS,
  readRegistry,
  containsPlaceholder,
  runChecks,
  validateRegistry,
  validateSecrets
};
