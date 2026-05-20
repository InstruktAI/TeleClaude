const fs = require('node:fs');
const path = require('node:path');

const AUTHORING_GUIDE =
  'software-development/procedure/snapshot-testing (docs/global/software-development/procedure/snapshot-testing.md)';

const EXEMPTIONS_PATH = '.teleclaude/snapshot-testing-exemptions.txt';
const FORBIDDEN_MATCHERS = new Set(['toBe', 'toEqual', 'toContain', 'toMatch', 'toStartWith', 'toEndWith']);
const BINARY_OPERATORS = new Set(['==', '===']);

function normalizePath(filename) {
  return filename.replaceAll('\\', '/');
}

function isTestFile(filename) {
  const normalized = normalizePath(filename);
  return (
    (/\/__tests__\/.*\.(ts|tsx)$/.test(normalized) || /(^|\/)[^/]+\.test\.(ts|tsx)$/.test(normalized)) &&
    !normalized.endsWith('.d.ts')
  );
}

function findProjectRoot(startDir) {
  let current = startDir;
  while (true) {
    if (fs.existsSync(path.join(current, EXEMPTIONS_PATH))) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return startDir;
    }
    current = parent;
  }
}

function loadExemptions(projectRoot) {
  const exemptionsFile = path.join(projectRoot, EXEMPTIONS_PATH);
  if (!fs.existsSync(exemptionsFile)) {
    return new Set();
  }
  const content = fs.readFileSync(exemptionsFile, 'utf8');
  return new Set(
    content
      .split(/\r?\n/)
      .map((line) => line.split('#', 1)[0].trim())
      .filter(Boolean)
      .map((line) => normalizePath(line)),
  );
}

function displayPath(filename, projectRoot) {
  const absolute = path.resolve(filename);
  const relative = path.relative(projectRoot, absolute);
  if (relative && !relative.startsWith('..') && !path.isAbsolute(relative)) {
    return normalizePath(relative);
  }
  return normalizePath(absolute);
}

function isExemptFile(filename, exemptions, projectRoot) {
  const normalized = normalizePath(filename);
  return exemptions.has(normalized) || exemptions.has(displayPath(filename, projectRoot));
}

function propertyName(node) {
  if (!node) {
    return null;
  }
  if (node.type === 'Identifier') {
    return node.name;
  }
  if (node.type === 'Literal' && typeof node.value === 'string') {
    return node.value;
  }
  return null;
}

function isStringLiteral(node) {
  if (!node) {
    return false;
  }
  if (node.type === 'Literal') {
    return typeof node.value === 'string' || Boolean(node.regex);
  }
  return node.type === 'TemplateLiteral' && node.expressions.length === 0;
}

function isMemberExpression(node) {
  return node && node.type === 'MemberExpression';
}

function isExpectChain(node) {
  if (!node) {
    return false;
  }
  if (node.type === 'CallExpression' && node.callee.type === 'Identifier' && node.callee.name === 'expect') {
    return true;
  }
  if (node.type === 'MemberExpression') {
    return isExpectChain(node.object);
  }
  return false;
}

function isCaughtExceptionMessage(node, catchBindings) {
  if (!isMemberExpression(node) || propertyName(node.property) !== 'message') {
    return false;
  }
  return node.object.type === 'Identifier' && catchBindings.has(node.object.name);
}

function report(context, node, pattern) {
  context.report({
    node,
    message: `snapshot-testing[${pattern}]: string content assertions must use snapshots, named constants, or a non-empty guard; see ${AUTHORING_GUIDE}`,
  });
}

const noStringAssertionsRule = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Detect forbidden string assertions in test files.',
    },
    schema: [],
  },
  create(context) {
    const filename = typeof context.getFilename === 'function' ? context.getFilename() : context.filename || '';
    const projectRoot = findProjectRoot(path.dirname(filename) || process.cwd());
    const exemptions = loadExemptions(projectRoot);
    if (!isTestFile(filename) || isExemptFile(filename, exemptions, projectRoot)) {
      return {};
    }

    const catchBindings = new Set();

    return {
      BinaryExpression(node) {
        if (!BINARY_OPERATORS.has(node.operator)) {
          return;
        }
        if (isStringLiteral(node.left) || isStringLiteral(node.right)) {
          report(context, node, 'assert_str_eq');
        }
      },
      CallExpression(node) {
        if (!isMemberExpression(node.callee)) {
          return;
        }
        const matcher = propertyName(node.callee.property);
        if (!matcher || !FORBIDDEN_MATCHERS.has(matcher) || !isExpectChain(node.callee.object)) {
          return;
        }
        if (node.arguments.some((argument) => isStringLiteral(argument))) {
          report(context, node, 'vitest_matcher');
        }
      },
      CatchClause(node) {
        if (node.param && node.param.type === 'Identifier') {
          catchBindings.add(node.param.name);
        }
      },
      'CatchClause:exit'(node) {
        if (node.param && node.param.type === 'Identifier') {
          catchBindings.delete(node.param.name);
        }
      },
      MemberExpression(node) {
        if (isCaughtExceptionMessage(node, catchBindings)) {
          report(context, node, 'exception_message');
        }
      },
    };
  },
};

module.exports = {
  rules: {
    'no-string-assertions': noStringAssertionsRule,
  },
};
