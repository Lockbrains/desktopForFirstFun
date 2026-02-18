import * as React from 'react'
import { Repository } from '../../models/repository'
import { ToolbarDropdown, DropdownState } from './dropdown'
import { ToolbarButtonStyle } from './button'
import * as octicons from '../octicons/octicons.generated'
import { TabBar } from '../tab-bar'
import { Button } from '../lib/button'
import { TextBox } from '../lib/text-box'
import { TextArea } from '../lib/text-area'
import { Select } from '../lib/select'
import { createBranch, deleteLocalBranch } from '../../lib/git/branch'
import { getCommits, getCommit } from '../../lib/git/log'
import { checkoutBranch } from '../../lib/git/checkout'
import { Branch, BranchType } from '../../models/branch'
import { formatAsLocalRef } from '../../lib/git/refs'
import { getBranches } from '../../lib/git/for-each-ref'
import { getContextLength, setContextLength } from '../../lib/gemini-api'

enum ReleaseTab {
  Release = 0,
  Settings = 1,
}

interface IReleaseDropdownProps {
  readonly repository: Repository
}

interface IReleaseDropdownState {
  readonly dropdownState: DropdownState
  readonly selectedTab: ReleaseTab
  readonly apiKey: string
  readonly releaseNote: string
  readonly isGenerating: boolean
  readonly isCreatingBranch: boolean
  readonly branchName: string
  readonly selectedModel: string
  readonly selectedThinking: string
  readonly releaseDescription: string
  readonly releaseBranches: ReadonlyArray<Branch>
  readonly isDeletingBranch: string | null
  readonly contextLength: number
}

export class ReleaseDropdown extends React.Component<
  IReleaseDropdownProps,
  IReleaseDropdownState
> {
  public constructor(props: IReleaseDropdownProps) {
    super(props)
    this.state = {
      dropdownState: 'closed',
      selectedTab: ReleaseTab.Release,
      apiKey: localStorage.getItem('gemini-api-key') || '',
      releaseNote: '',
      isGenerating: false,
      isCreatingBranch: false,
      branchName: this.generateBranchName(),
      selectedModel: 'gemini-3-flash-preview',
      selectedThinking: 'high',
      releaseDescription: 'No release branch exists',
      releaseBranches: [],
      isDeletingBranch: null,
      contextLength: getContextLength(),
    }
  }

  public componentDidMount() {
    this.loadReleaseBranches()
  }

  private generateBranchName(): string {
    const now = new Date()
    const mm = String(now.getMonth() + 1).padStart(2, '0')
    const dd = String(now.getDate()).padStart(2, '0')
    const yy = String(now.getFullYear()).slice(-2)
    return `release${mm}${dd}${yy}`
  }

  private async loadReleaseBranches() {
    try {
      const allBranches = await getBranches(this.props.repository, 'refs/heads')
      const releaseBranches = allBranches.filter(b =>
        b.name.toLowerCase().includes('release')
      )

      let releaseDescription = 'No release branch exists'
      if (releaseBranches.length > 0) {
        // Find the latest release branch by name (sorted descending)
        const sorted = [...releaseBranches].sort((a, b) =>
          b.name.localeCompare(a.name)
        )
        const latest = sorted[0].name
        // Try to extract date from releaseMMDDYY format
        const match = latest.match(/release(\d{2})(\d{2})(\d{2})/)
        if (match) {
          releaseDescription = `Last release on ${match[1]}/${match[2]}/${match[3]}`
        } else {
          releaseDescription = `Latest: ${latest}`
        }
      }

      this.setState({ releaseBranches, releaseDescription })
    } catch (e) {
      // silently fail - just keep default description
    }
  }

  private onDropDownStateChanged = (state: DropdownState) => {
    this.setState({ dropdownState: state })
    if (state === 'open') {
      this.loadReleaseBranches()
    }
  }

  private onTabClicked = (index: number) => {
    this.setState({ selectedTab: index })
  }

  private onApiKeyChange = (value: string) => {
    this.setState({ apiKey: value })
    localStorage.setItem('gemini-api-key', value)
  }

  private onReleaseNoteChange = (event: React.FormEvent<HTMLTextAreaElement>) => {
    this.setState({ releaseNote: event.currentTarget.value })
  }
  
  private onModelChange = (event: React.FormEvent<HTMLSelectElement>) => {
      this.setState({ selectedModel: event.currentTarget.value })
  }

  private onThinkingChange = (event: React.FormEvent<HTMLSelectElement>) => {
      this.setState({ selectedThinking: event.currentTarget.value })
  }

  private onContextLengthChange = (value: string) => {
      const num = parseInt(value, 10)
      if (!isNaN(num) && num > 0) {
        this.setState({ contextLength: num })
        setContextLength(num)
      }
  }

  private onCreateReleaseBranch = async () => {
    const { repository } = this.props
    const { branchName } = this.state
    
    this.setState({ isCreatingBranch: true })
    
    try {
      await createBranch(repository, branchName, 'main')
      const tipCommit = await getCommit(repository, branchName)
      if (!tipCommit) {
        throw new Error('Could not find tip of new branch')
      }

      const branch = new Branch(
        branchName,
        null, 
        { sha: tipCommit.sha },
        BranchType.Local,
        formatAsLocalRef(branchName)
      )
      
      await checkoutBranch(repository, branch, null)
      await this.loadReleaseBranches()
      alert(`Successfully created and checked out branch: ${branchName}`)
    } catch (e) {
      alert(`Failed to create branch: ${e}`)
    } finally {
      this.setState({ isCreatingBranch: false })
    }
  }

  private onDeleteReleaseBranch = async (branchName: string) => {
    const { repository } = this.props

    if (!confirm(`Are you sure you want to delete branch "${branchName}"?`)) {
      return
    }

    this.setState({ isDeletingBranch: branchName })

    try {
      await deleteLocalBranch(repository, branchName)
      await this.loadReleaseBranches()
    } catch (e) {
      alert(`Failed to delete branch: ${e}`)
    } finally {
      this.setState({ isDeletingBranch: null })
    }
  }

  private onGenerateReleaseNote = async () => {
    const { repository } = this.props
    const { apiKey, selectedModel, selectedThinking, contextLength } = this.state

    if (!apiKey) {
      alert('Please enter your Gemini API Key in Settings.')
      return
    }

    this.setState({ isGenerating: true })

    try {
      // Use --first-parent to only get commits merged to main (per CHANGELOG_INSTRUCTIONS.md)
      const commits = await getCommits(
        repository,
        'main',
        contextLength,
        undefined,
        ['--first-parent']
      )
      const commitMessages = commits
        .map(c => `- [${c.shortSha}] ${c.summary}${c.body ? '\n  ' + c.body.trim() : ''}`)
        .join('\n')

      const prompt = `You are a release note generator for a game project called "Wingstrike" (a mobile aerial combat game). Based on the following git commit logs from the main branch, generate TWO sections of release notes following our project's changelog instructions.

## Commit Logs (last ${contextLength} commits, --first-parent only):
${commitMessages}

---

## Instructions:

### SECTION 1: Technical Changelog
Generate a technical changelog using these categories:
- **Added** - New features, systems, components, or capabilities
- **Changed** - Modifications to existing functionality
- **Fixed** - Bug fixes and issue resolutions
- **Performance** - Optimizations and performance improvements
- **Assets** - Art, UI, sprites, models, animations
- **Technical** - Backend changes, refactoring, architecture
- **Removed** - Deleted features or deprecated code

Format each entry as: - [Component/System] Description of change
Include ALL code changes comprehensively. Include specific class/component names, technical details, and PR numbers if visible in commit messages.

### SECTION 2: Public Release Notes (User-Facing)
Transform technical changes into user-facing benefits using these categories:
- **New Features** - Exciting new content
- **Improvements** - Better experience
- **Bug Fixes** - Stability improvements
- **Balance Changes** - Gameplay adjustments

Translation rules (System → Feature mapping):
- Combat Systems → "Aerial combat mechanics"
- Movement Systems → "Flight controls"
- UI Systems → "Interface improvements"
- Inventory/Item Systems → "Aircraft and pilot collection"
- AI Systems → "Enemy squadron behavior"
- Network Systems → "Online features"
- Audio Systems → "Sound and music"
- Visual Systems → "Graphics and effects"
- Weapon Systems → "Aircraft armaments"
- Buff Systems → "Upgrade stacking"
- Power-up Systems → "In-flight bonuses"
- Wingman Systems → "Squadron support"
- Hangar Systems → "Aircraft collection"
- Gacha Systems → "Pilot and plane unlocks"

Common fixes translation:
- Null reference exceptions → "Stability improvements"
- Memory leaks → "Performance optimization"
- Shader issues → "Visual improvements"
- Input handling → "Control responsiveness"
- Save/load bugs → "Progress saving fixes"
- Collision detection → "Gameplay fixes"

EXCLUDE from public notes:
- Technical implementation details, class/component/system names
- PR numbers or commit hashes
- Internal tool changes (Excel Merge Tool, Level Visualizer, Editor scripts, build tools)
- Developer tools and workflows
- Documentation files
- Features not in playable content or disabled features

Public tone should be exciting, positive, and use simple non-technical language.

### OUTPUT FORMAT:
Output the two sections clearly separated with headers:
\`\`\`
## Technical Changelog

[entries here]

## Public Release Notes

[entries here]
\`\`\``

      // Build Gemini API request body with thinking config
      const thinkingBudget = selectedThinking === 'high' ? 8192 : 2048
      const requestBody: Record<string, unknown> = {
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          thinkingConfig: {
            thinkingBudget: thinkingBudget,
          },
        },
      }

      const response = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${selectedModel}:generateContent?key=${apiKey}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        }
      )

      if (!response.ok) {
        const errorBody = await response.text()
        throw new Error(`API call failed (${response.status}): ${errorBody}`)
      }

      const data = await response.json()
      const generatedText = data.candidates?.[0]?.content?.parts?.[0]?.text || 'No content generated.'

      this.setState({ releaseNote: generatedText })
    } catch (e) {
      alert(`Failed to generate release note: ${e}`)
    } finally {
      this.setState({ isGenerating: false })
    }
  }

  private renderReleaseBranchesList() {
    const { releaseBranches, isDeletingBranch } = this.state

    if (releaseBranches.length === 0) {
      return (
        <div style={{ padding: '8px 0', fontSize: '12px', color: 'var(--text-secondary)', textAlign: 'center' }}>
          No release branches found
        </div>
      )
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {releaseBranches.map(branch => (
          <div
            key={branch.name}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '4px 8px',
              borderRadius: '3px',
              backgroundColor: 'var(--box-alt-background-color)',
              fontSize: '12px',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              {branch.name}
            </span>
            <button
              onClick={() => this.onDeleteReleaseBranch(branch.name)}
              disabled={isDeletingBranch === branch.name}
              style={{
                marginLeft: '8px',
                padding: '2px 8px',
                fontSize: '11px',
                cursor: 'pointer',
                border: '1px solid var(--secondary-button-border-color)',
                borderRadius: '3px',
                backgroundColor: 'transparent',
                color: 'var(--text-color)',
                opacity: isDeletingBranch === branch.name ? 0.5 : 1,
              }}
            >
              {isDeletingBranch === branch.name ? '...' : 'Delete'}
            </button>
          </div>
        ))}
      </div>
    )
  }

  private renderReleaseTab() {
    return (
      <div style={{ padding: '15px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Button 
            onClick={this.onCreateReleaseBranch}
            disabled={this.state.isCreatingBranch}
          >
            {this.state.isCreatingBranch ? 'Creating...' : 'Create Release Branch'}
          </Button>
          
          <Button 
            onClick={this.onGenerateReleaseNote}
            disabled={this.state.isGenerating}
          >
            {this.state.isGenerating ? 'Generating...' : 'Read Release Note'}
          </Button>

          <Button onClick={() => alert('Documentation not available yet')}>
            Read Documentation
          </Button>
        </div>
        
        {this.state.releaseNote && (
          <TextArea
            label="Generated Note"
            value={this.state.releaseNote}
            onChange={this.onReleaseNoteChange}
            rows={10}
          />
        )}

        <div style={{ borderTop: '1px solid var(--box-border-color)', paddingTop: '10px' }}>
          <h3 style={{ fontSize: '12px', fontWeight: 600, margin: '0 0 8px 0' }}>
            Release Branches ({this.state.releaseBranches.length})
          </h3>
          {this.renderReleaseBranchesList()}
        </div>
      </div>
    )
  }

  private renderSettingsTab() {
    return (
      <div style={{ padding: '15px', display: 'flex', flexDirection: 'column', gap: '15px' }}>
         <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '5px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: 600, margin: 0 }}>API Configuration</h3>
            <TextBox
              placeholder="Enter your API Key"
              value={this.state.apiKey}
              onValueChanged={this.onApiKeyChange}
              type="password"
            />
            <p style={{ fontSize: '11px', color: 'var(--text-secondary)', margin: 0 }}>
              Get your API Key at <a href="https://aistudio.google.com/" target="_blank" rel="noopener noreferrer">Google AI Studio</a> using our developer account developer@firstfun.com.
            </p>
         </div>

         <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '10px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: 600, margin: 0 }}>Model Selection</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '12px' }}>Model</label>
              <Select value={this.state.selectedModel} onChange={this.onModelChange} >
                  <option value="gemini-3-flash-preview">Gemini-3-Flash</option>
                  <option value="gemini-3-pro-preview">Gemini-3-Pro</option>
              </Select>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '12px' }}>Thinking</label>
              <Select value={this.state.selectedThinking} onChange={this.onThinkingChange} >
                  <option value="high">High (Default)</option>
                  <option value="low">Low</option>
              </Select>
            </div>
         </div>

         <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '5px' }}>
            <h3 style={{ fontSize: '12px', fontWeight: 600, margin: 0 }}>AI Agent Settings</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '12px' }}>Context Length</label>
              <input
                type="number"
                min="1"
                max="100"
                value={this.state.contextLength}
                onChange={(e) => this.onContextLengthChange(e.currentTarget.value)}
                style={{
                  width: '80px',
                  textAlign: 'right',
                  padding: '4px 8px',
                  border: '1px solid var(--box-border-color)',
                  borderRadius: '4px',
                  backgroundColor: 'var(--box-background-color)',
                  color: 'var(--text-color)',
                  fontSize: '12px',
                }}
              />
            </div>
            <p style={{ fontSize: '11px', color: 'var(--text-secondary)', margin: 0 }}>
              Number of messages to include as context when chatting with the AI agent. Higher values provide more context but use more tokens.
            </p>
         </div>
      </div>
    )
  }

  private renderDropdownContent = (): JSX.Element => {
    return (
      <div style={{ width: '400px', maxHeight: '600px', display: 'flex', flexDirection: 'column' }}>
        <TabBar
          onTabClicked={this.onTabClicked}
          selectedIndex={this.state.selectedTab}
        >
          <span>Release</span>
          <span>Settings</span>
        </TabBar>
        <div style={{ flex: 1, overflowY: 'auto' }}>
            {this.state.selectedTab === ReleaseTab.Release
                ? this.renderReleaseTab()
                : this.renderSettingsTab()}
        </div>
      </div>
    )
  }

  public render() {
    return (
      <ToolbarDropdown
        title="Release & AI"
        description={this.state.releaseDescription}
        icon={octicons.rocket}
        style={ToolbarButtonStyle.Subtitle}
        dropdownContentRenderer={this.renderDropdownContent}
        dropdownState={this.state.dropdownState}
        onDropdownStateChanged={this.onDropDownStateChanged}
      />
    )
  }
}
