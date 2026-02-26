/**
 * Agent tool declarations and execution logic.
 * Defines all tools available to the Gemini agent and how to execute them.
 */

import { git } from './git/core'
import { Repository } from '../models/repository'
import * as https from 'https'
import * as http from 'http'
import { URL } from 'url'

/** A single action executed by the agent */
export interface IAgentAction {
  readonly tool: string
  readonly args: Record<string, any>
  readonly result: string
  readonly success: boolean
}

/**
 * Tool declarations for the Gemini function calling API.
 * These define what tools the agent can use.
 */
export const agentToolDeclarations = [
  {
    name: 'git_status',
    description:
      'Get the current git status, showing modified, staged, and untracked files',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'git_add',
    description:
      'Stage files for the next commit. Use files=["."] to stage all changes.',
    parameters: {
      type: 'OBJECT',
      properties: {
        files: {
          type: 'ARRAY',
          items: { type: 'STRING' },
          description:
            'List of file paths to stage, or ["."] to stage all changes',
        },
      },
      required: ['files'],
    },
  },
  {
    name: 'git_commit',
    description: 'Create a new commit with the staged changes',
    parameters: {
      type: 'OBJECT',
      properties: {
        message: { type: 'STRING', description: 'The commit message' },
      },
      required: ['message'],
    },
  },
  {
    name: 'git_push',
    description: 'Push local commits to the remote repository',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'git_pull',
    description: 'Pull latest changes from the remote repository',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'git_log',
    description: 'View recent commit history',
    parameters: {
      type: 'OBJECT',
      properties: {
        count: {
          type: 'INTEGER',
          description: 'Number of commits to show (default: 10)',
        },
      },
    },
  },
  {
    name: 'git_diff',
    description: 'Show the current uncommitted changes (diff)',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'git_branch_list',
    description: 'List all local branches',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'git_checkout',
    description: 'Switch to a different branch',
    parameters: {
      type: 'OBJECT',
      properties: {
        branch: {
          type: 'STRING',
          description: 'Name of the branch to switch to',
        },
      },
      required: ['branch'],
    },
  },
  {
    name: 'git_create_branch',
    description:
      'Create a new git branch. Does NOT switch to it automatically.',
    parameters: {
      type: 'OBJECT',
      properties: {
        name: { type: 'STRING', description: 'Name of the new branch' },
        start_point: {
          type: 'STRING',
          description:
            'Start point (commit, branch) for the branch. Default: current HEAD',
        },
      },
      required: ['name'],
    },
  },
  {
    name: 'create_release_branch',
    description:
      'Create a release branch with standard naming convention (releaseMMDDYY) from main, and switch to it',
    parameters: {
      type: 'OBJECT',
      properties: {
        name: {
          type: 'STRING',
          description:
            "Optional custom branch name. If not provided, auto-generates releaseMMDDYY based on today's date",
        },
      },
    },
  },
  {
    name: 'generate_release_notes',
    description:
      'Generate release notes from recent commit history using AI summarization',
    parameters: {
      type: 'OBJECT',
      properties: {
        commit_count: {
          type: 'INTEGER',
          description:
            'Number of recent commits to include (default: 20)',
        },
      },
    },
  },
  {
    name: 'trigger_build',
    description:
      'Trigger a Jenkins CI/CD build pipeline. Supports 4 combinations: iOS Debug, iOS Release, Android Debug, Android Release.',
    parameters: {
      type: 'OBJECT',
      properties: {
        platform: {
          type: 'STRING',
          description: 'Target platform: "ios" or "android"',
          enum: ['ios', 'android'],
        },
        build_mode: {
          type: 'STRING',
          description: 'Build mode: "debug" or "release"',
          enum: ['debug', 'release'],
        },
        branch: {
          type: 'STRING',
          description:
            'Branch to build from. Default: current branch.',
        },
        build_type: {
          type: 'STRING',
          description:
            'For Android: "APK" or "HotUpdate". For iOS: "App" or "HotUpdate". Default: APK for Android, App for iOS.',
        },
        install_type: {
          type: 'STRING',
          description:
            'iOS only. "Adhoc", "Xcode", or "TestFlight" (TestFlight only for release). Default: "Adhoc".',
        },
      },
      required: ['platform', 'build_mode'],
    },
  },
  {
    name: 'git_reset',
    description:
      'Unstage files or reset to a previous state. Default: unstage all staged files (mixed reset).',
    parameters: {
      type: 'OBJECT',
      properties: {
        mode: {
          type: 'STRING',
          description:
            'Reset mode: "soft", "mixed", or "hard". Default: "mixed".',
        },
        target: {
          type: 'STRING',
          description:
            'Target ref to reset to (e.g. HEAD~1, a commit SHA). Default: HEAD.',
        },
      },
    },
  },
  {
    name: 'git_stash',
    description: 'Stash or restore stashed changes',
    parameters: {
      type: 'OBJECT',
      properties: {
        action: {
          type: 'STRING',
          description:
            'Action: "push" (stash changes), "pop" (restore latest stash), "list" (list stashes). Default: "push".',
        },
        message: {
          type: 'STRING',
          description: 'Optional stash message (for push action)',
        },
      },
    },
  },
]

/**
 * Execute an agent tool and return the result string.
 *
 * @param name The tool name
 * @param args The tool arguments
 * @param repository The current repository
 * @returns Result string describing what happened
 */
export async function executeAgentTool(
  name: string,
  args: Record<string, any>,
  repository: Repository
): Promise<string> {
  try {
    switch (name) {
      case 'git_status':
        return await executeGitStatus(repository)
      case 'git_add':
        return await executeGitAdd(repository, args.files || ['.'])
      case 'git_commit':
        return await executeGitCommit(repository, args.message)
      case 'git_push':
        return await executeGitPush(repository)
      case 'git_pull':
        return await executeGitPull(repository)
      case 'git_log':
        return await executeGitLog(repository, args.count || 10)
      case 'git_diff':
        return await executeGitDiff(repository)
      case 'git_branch_list':
        return await executeGitBranchList(repository)
      case 'git_checkout':
        return await executeGitCheckout(repository, args.branch)
      case 'git_create_branch':
        return await executeGitCreateBranch(
          repository,
          args.name,
          args.start_point
        )
      case 'create_release_branch':
        return await executeCreateReleaseBranch(repository, args.name)
      case 'generate_release_notes':
        return await executeGenerateReleaseNotes(
          repository,
          args.commit_count || 20
        )
      case 'trigger_build':
        return await executeTriggerBuild(repository, args)
      case 'git_reset':
        return await executeGitReset(
          repository,
          args.mode || 'mixed',
          args.target || 'HEAD'
        )
      case 'git_stash':
        return await executeGitStash(
          repository,
          args.action || 'push',
          args.message
        )
      default:
        return `Unknown tool: ${name}`
    }
  } catch (error) {
    const message =
      error instanceof Error ? error.message : String(error)
    return `Error executing ${name}: ${message}`
  }
}

// ── Git tool implementations ──────────────────────────────────────────

async function executeGitStatus(repository: Repository): Promise<string> {
  const result = await git(
    ['status'],
    repository.path,
    'agentGitStatus',
    { successExitCodes: new Set([0, 1, 128]) }
  )
  return result.stdout || result.stderr || 'No output from git status'
}

async function executeGitAdd(
  repository: Repository,
  files: string[]
): Promise<string> {
  const args = ['add', '--', ...files]
  await git(args, repository.path, 'agentGitAdd')
  return `Successfully staged: ${files.join(', ')}`
}

async function executeGitCommit(
  repository: Repository,
  message: string
): Promise<string> {
  if (!message) {
    return 'Error: Commit message is required'
  }
  const result = await git(
    ['commit', '-m', message],
    repository.path,
    'agentGitCommit'
  )
  return result.stdout || 'Commit created successfully'
}

async function executeGitPush(repository: Repository): Promise<string> {
  const result = await git(
    ['push'],
    repository.path,
    'agentGitPush',
    { successExitCodes: new Set([0, 1]) }
  )
  return (
    result.stdout ||
    result.stderr ||
    'Push completed'
  )
}

async function executeGitPull(repository: Repository): Promise<string> {
  const result = await git(
    ['pull'],
    repository.path,
    'agentGitPull',
    { successExitCodes: new Set([0, 1]) }
  )
  return (
    result.stdout ||
    result.stderr ||
    'Pull completed'
  )
}

async function executeGitLog(
  repository: Repository,
  count: number
): Promise<string> {
  const result = await git(
    ['log', `--oneline`, `-${count}`],
    repository.path,
    'agentGitLog',
    { successExitCodes: new Set([0, 128]) }
  )
  return result.stdout || 'No commits found'
}

async function executeGitDiff(repository: Repository): Promise<string> {
  const result = await git(
    ['diff'],
    repository.path,
    'agentGitDiff',
    { successExitCodes: new Set([0, 1]) }
  )
  if (!result.stdout) {
    // Try staged diff
    const stagedResult = await git(
      ['diff', '--staged'],
      repository.path,
      'agentGitDiffStaged',
      { successExitCodes: new Set([0, 1]) }
    )
    return stagedResult.stdout || 'No changes detected'
  }
  return result.stdout
}

async function executeGitBranchList(
  repository: Repository
): Promise<string> {
  const result = await git(
    ['branch', '-a'],
    repository.path,
    'agentGitBranchList'
  )
  return result.stdout || 'No branches found'
}

async function executeGitCheckout(
  repository: Repository,
  branch: string
): Promise<string> {
  if (!branch) {
    return 'Error: Branch name is required'
  }
  await git(
    ['checkout', branch],
    repository.path,
    'agentGitCheckout'
  )
  return `Switched to branch: ${branch}`
}

async function executeGitCreateBranch(
  repository: Repository,
  name: string,
  startPoint?: string
): Promise<string> {
  if (!name) {
    return 'Error: Branch name is required'
  }
  const args = startPoint
    ? ['branch', name, startPoint]
    : ['branch', name]
  await git(args, repository.path, 'agentGitCreateBranch')
  return `Created branch: ${name}${
    startPoint ? ` from ${startPoint}` : ''
  }`
}

async function executeCreateReleaseBranch(
  repository: Repository,
  customName?: string
): Promise<string> {
  const now = new Date()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  const yy = String(now.getFullYear()).slice(-2)
  const branchName = customName || `release${mm}${dd}${yy}`

  // Create from main
  await git(
    ['branch', branchName, 'main'],
    repository.path,
    'agentCreateReleaseBranch'
  )
  // Checkout the new branch
  await git(
    ['checkout', branchName],
    repository.path,
    'agentCheckoutReleaseBranch'
  )
  return `Created and checked out release branch: ${branchName}`
}

async function executeGenerateReleaseNotes(
  repository: Repository,
  commitCount: number
): Promise<string> {
  const apiKey = localStorage.getItem('gemini-api-key') || ''
  if (!apiKey) {
    return 'Error: Gemini API key not configured. Please set it in Release & AI > Settings.'
  }

  const result = await git(
    ['log', `--oneline`, `-${commitCount}`],
    repository.path,
    'agentGetCommitsForReleaseNotes'
  )

  const commitMessages = result.stdout
  if (!commitMessages) {
    return 'No commits found to generate release notes from.'
  }

  const model = localStorage.getItem('gemini-chat-model') || 'gemini-3-flash-preview'
  const prompt = `Please generate a release note based on the following git commit logs. Format it nicely with sections like "Features", "Fixes", "Improvements" etc.\n\n${commitMessages}`

  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
      }),
    }
  )

  if (!response.ok) {
    return `Failed to generate release notes: API returned ${response.status}`
  }

  const data = await response.json()
  return (
    data.candidates?.[0]?.content?.parts?.[0]?.text ||
    'No release notes generated.'
  )
}

// ── Jenkins Build ─────────────────────────────────────────────────────

const JENKINS_BASE_HOST = 'http://192.168.50.249:8080'

const PIPELINE_MAP: Record<string, string> = {
  'ios-debug': 'StarFire-iOS-Debug-Pipeline',
  'ios-release': 'StarFire-iOS-Release-Pipeline',
  'android-debug': 'StarFire-Android-Debug-Pipeline',
  'android-release': 'StarFire-Android-Release',
}

function jenkinsHttpRequest(
  urlStr: string,
  options: {
    method?: string
    headers?: Record<string, string>
    body?: string
  }
): Promise<{ statusCode: number; headers: http.IncomingHttpHeaders; body: string }> {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr)
    const client = url.protocol === 'https:' ? https : http
    const reqOptions = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,
      method: options.method || 'GET',
      headers: options.headers,
    }

    const req = client.request(reqOptions, res => {
      let data = ''
      res.on('data', (chunk: any) => {
        data += chunk
      })
      res.on('end', () => {
        resolve({
          statusCode: res.statusCode || 0,
          headers: res.headers,
          body: data,
        })
      })
    })

    req.on('error', (e: Error) => {
      reject(e)
    })

    if (options.body) {
      req.write(options.body)
    }
    req.end()
  })
}

async function executeTriggerBuild(
  repository: Repository,
  args: Record<string, any>
): Promise<string> {
  const { platform, build_mode, branch, build_type, install_type } = args

  const pipelineKey = `${platform}-${build_mode}`
  const selectedPipeline = PIPELINE_MAP[pipelineKey]
  if (!selectedPipeline) {
    return `Error: Invalid platform/mode combination: ${platform}/${build_mode}. Valid: ios-debug, ios-release, android-debug, android-release.`
  }

  const jenkinsUser = localStorage.getItem('jenkins-user') || ''
  const jenkinsToken = localStorage.getItem('jenkins-token') || ''

  const authHeaders: Record<string, string> = {}
  if (jenkinsUser && jenkinsToken) {
    authHeaders['Authorization'] =
      'Basic ' +
      Buffer.from(`${jenkinsUser}:${jenkinsToken}`).toString('base64')
  }

  // Determine defaults
  const isIOS = platform === 'ios'
  const isDebug = build_mode === 'debug'

  // Get current branch if not specified
  let buildBranch = branch
  if (!buildBranch) {
    try {
      const branchResult = await git(
        ['rev-parse', '--abbrev-ref', 'HEAD'],
        repository.path,
        'agentGetCurrentBranch'
      )
      buildBranch = branchResult.stdout.trim()
    } catch {
      buildBranch = 'main'
    }
  }

  const finalBuildType =
    build_type || (isIOS ? 'App' : 'APK')
  const finalTableEnv = 'dev' // 固定 dev，不提供修改
  const finalInstallType = install_type || 'Adhoc'

  // Fetch crumb
  let crumbHeader: Record<string, string> = {}
  let cookieHeader: string | undefined

  try {
    const crumbResp = await jenkinsHttpRequest(
      `${JENKINS_BASE_HOST}/crumbIssuer/api/json`,
      { headers: authHeaders }
    )
    if (crumbResp.statusCode === 200) {
      const crumbData = JSON.parse(crumbResp.body)
      if (crumbData.crumb && crumbData.crumbRequestField) {
        crumbHeader = { [crumbData.crumbRequestField]: crumbData.crumb }
      }
      if (crumbResp.headers['set-cookie']) {
        const cookies = crumbResp.headers['set-cookie']
        cookieHeader = (Array.isArray(cookies) ? cookies : [cookies])
          .map((c: string) => c.split(';')[0])
          .join('; ')
      }
    }
  } catch {
    // Continue without crumb
  }

  // Build params
  const params = new URLSearchParams()
  params.append('BuildType', finalBuildType)
  params.append('BRANCH', buildBranch)
  params.append('TABLE_ENV', finalTableEnv)
  params.append('SIMULATE_ONLINE', 'false')
  params.append('PACK_ALL', 'false')
  params.append('CLEAR_CACHE', 'false')
  params.append('USE_DEBUG_HOT_UPDATE', isDebug ? 'true' : 'false')

  if (isIOS) {
    params.append('InstallType', finalInstallType)
  }

  const buildUrl = `${JENKINS_BASE_HOST}/job/${selectedPipeline}/buildWithParameters?${params.toString()}`
  const buildHeaders: Record<string, string> = {
    ...authHeaders,
    ...crumbHeader,
  }
  if (cookieHeader) {
    buildHeaders['Cookie'] = cookieHeader
  }

  const response = await jenkinsHttpRequest(buildUrl, {
    method: 'POST',
    headers: buildHeaders,
  })

  if (response.statusCode >= 200 && response.statusCode < 300) {
    return `✅ Successfully triggered build!\n` +
      `Pipeline: ${selectedPipeline}\n` +
      `Branch: ${buildBranch}\n` +
      `Build Type: ${finalBuildType}\n` +
      `Table Env: ${finalTableEnv}` +
      (isIOS ? `\nInstall Type: ${finalInstallType}` : '')
  } else {
    return `❌ Failed to trigger build: HTTP ${response.statusCode}\n${response.body}`
  }
}

// ── Git Reset & Stash ─────────────────────────────────────────────────

async function executeGitReset(
  repository: Repository,
  mode: string,
  target: string
): Promise<string> {
  const validModes = ['soft', 'mixed', 'hard']
  if (!validModes.includes(mode)) {
    return `Error: Invalid reset mode "${mode}". Valid: ${validModes.join(', ')}`
  }
  const result = await git(
    ['reset', `--${mode}`, target],
    repository.path,
    'agentGitReset'
  )
  return result.stdout || `Reset (${mode}) to ${target} completed`
}

async function executeGitStash(
  repository: Repository,
  action: string,
  message?: string
): Promise<string> {
  switch (action) {
    case 'push': {
      const args = message
        ? ['stash', 'push', '-m', message]
        : ['stash', 'push']
      const result = await git(args, repository.path, 'agentGitStash')
      return result.stdout || 'Changes stashed'
    }
    case 'pop': {
      const result = await git(
        ['stash', 'pop'],
        repository.path,
        'agentGitStashPop'
      )
      return result.stdout || 'Stash applied and removed'
    }
    case 'list': {
      const result = await git(
        ['stash', 'list'],
        repository.path,
        'agentGitStashList',
        { successExitCodes: new Set([0, 1]) }
      )
      return result.stdout || 'No stashes found'
    }
    default:
      return `Error: Unknown stash action "${action}". Valid: push, pop, list`
  }
}



