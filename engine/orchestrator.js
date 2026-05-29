const fs = require('fs');

function parseCommand(cmd) {
  const match = cmd.match(/Deploy\s+([a-z-]+)(?:\s+to\s+(production|staging))?/i);
  if (!match) throw new Error('Invalid command format. Expected: "Deploy <repo> to <env>"');
  
  return {
    repo: match[1],
    env: match[2] || 'production'
  };
}

function getRepoConfig(repoId) {
  // Read synchronously to ensure config exists before proceeding
  const registry = JSON.parse(fs.readFileSync('registry/repos.json', 'utf8'));
  return registry.repos.find(r => r.id === repoId);
}

// Execute natively in GitHub Actions
if (require.main === module) {
  const cmd = process.argv[2];
  if (!cmd) {
    console.error('❌ No command provided');
    process.exit(1);
  }

  const parsed = parseCommand(cmd);
  const config = getRepoConfig(parsed.repo);

  if (!config) {
    console.error(`❌ Repository '${parsed.repo}' not found in registry/repos.json`);
    process.exit(1);
  }

  // Format outputs for GitHub Actions
  const output = `repo=${parsed.repo}\nenv=${parsed.env}\nplatform=${config.platform}\nproject_id=${config.project_id || ''}\nservice_id=${config.service_id || ''}\n`;
  
  fs.appendFileSync(process.env.GITHUB_OUTPUT, output);
  console.log(`✅ Orchestrator parsed: ${parsed.repo} (${config.platform}) -> ${parsed.env}`);
}

module.exports = { parseCommand, getRepoConfig };
