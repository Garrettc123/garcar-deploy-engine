// Garcar Deploy Engine Orchestrator
const fs = require('fs');

function parseCommand(cmd) {
  const match = cmd.match(/Deploy\s+([a-z-]+)(?:\s+to\s+(production|staging))?/i);
  if (!match) throw new Error('Invalid command format');
  
  return {
    repo: match[1],
    env: match[2] || 'production'
  };
}

function getRepoConfig(repoId) {
  const registry = JSON.parse(fs.readFileSync('registry/repos.json'));
  return registry.repos.find(r => r.id === repoId);
}

module.exports = { parseCommand, getRepoConfig };
