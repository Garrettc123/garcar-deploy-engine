const fs = require('fs');

const ALLOWED_ENVS = new Set(['staging', 'production']);
const REPO_ID = /^[a-z0-9][a-z0-9-]*$/;

function parseCommand(cmd) {
  if (typeof cmd !== 'string' || cmd.length > 200) {
    throw new Error('Invalid deploy command');
  }

  const match = cmd.trim().match(/^Deploy\s+([a-z0-9][a-z0-9-]*)(?:\s+to\s+(production|staging))?$/i);
  if (!match) throw new Error('Invalid command format. Expected: "Deploy <repo> to <env>"');

  const repo = match[1].toLowerCase();
  const env = (match[2] || 'production').toLowerCase();
  if (!REPO_ID.test(repo) || !ALLOWED_ENVS.has(env)) throw new Error('Invalid repository or environment');

  return { repo, env };
}

function getRepoConfig(repoId) {
  const registry = JSON.parse(fs.readFileSync('registry/repos.json', 'utf8'));
  const config = registry.repos.find(r => r.id === repoId);
  if (!config) return undefined;

  const required = ['id', 'platform', 'repo_url'];
  for (const key of required) {
    if (!config[key] || typeof config[key] !== 'string') {
      throw new Error(`Registry entry '${repoId}' is missing '${key}'`);
    }
  }

  if (config.id !== repoId) throw new Error('Registry identity mismatch');
  if (!['railway', 'vercel'].includes(config.platform)) {
    throw new Error(`Unsupported deployment platform: ${config.platform}`);
  }

  for (const value of Object.values(config)) {
    if (typeof value === 'string' && value.includes('replace-with-')) {
      throw new Error(`Registry entry '${repoId}' contains an unresolved deployment placeholder`);
    }
  }

  return config;
}

if (require.main === module) {
  try {
    const parsed = parseCommand(process.argv[2]);
    const config = getRepoConfig(parsed.repo);
    if (!config) throw new Error(`Repository '${parsed.repo}' not found in registry/repos.json`);

    const output = [
      `repo=${parsed.repo}`,
      `env=${parsed.env}`,
      `platform=${config.platform}`,
      `project_id=${config.project_id || ''}`,
      `service_id=${config.service_id || ''}`,
      `repo_url=${config.repo_url}`
    ].join('\n') + '\n';

    if (!process.env.GITHUB_OUTPUT) throw new Error('GITHUB_OUTPUT is not available');
    fs.appendFileSync(process.env.GITHUB_OUTPUT, output, { encoding: 'utf8' });
    console.log(`Validated: ${parsed.repo} (${config.platform}) -> ${parsed.env}`);
  } catch (error) {
    console.error(`Deployment validation failed: ${error.message}`);
    process.exit(1);
  }
}

module.exports = { parseCommand, getRepoConfig };
