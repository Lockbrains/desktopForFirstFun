import * as React from 'react'
import {
  IChatMessage,
  GeminiModel,
  sendGeminiAgentMessage,
  getGeminiApiKey,
  getGeminiModel,
  setGeminiModel,
  getModelDisplayName,
  IAgentResponse,
} from '../../lib/gemini-api'
import { IAgentAction } from '../../lib/agent-tools'
import { Repository } from '../../models/repository'
import { Account } from '../../models/account'
import { Avatar } from '../lib/avatar'

interface IGeminiChatProps {
  /**
   * The current repository, used for executing agent actions
   */
  readonly repository: Repository

  /** The logged in accounts, used for displaying the user avatar */
  readonly accounts: ReadonlyArray<Account>

  /**
   * Callback fired when the message list changes (message added or cleared).
   * Parent components use this to decide whether to show the normal view
   * or the full chat view.
   */
  readonly onMessagesChange?: () => void
}

interface IGeminiChatState {
  readonly messages: ReadonlyArray<IChatMessage>
  readonly inputText: string
  readonly isLoading: boolean
  readonly selectedModel: GeminiModel
  readonly showModelSelector: boolean
  readonly error: string | null
  /** Actions currently being executed (shown as live updates) */
  readonly pendingActions: ReadonlyArray<IAgentAction>
}

/**
 * A chat panel component that communicates with the Gemini API.
 * Shows an input field at the bottom. When messages are sent,
 * the area above becomes a scrollable chat bubble interface.
 *
 * Supports agent capabilities: the model can call tools (git commands,
 * release management, build triggers) and results are displayed
 * inline as action bubbles.
 */
export class GeminiChat extends React.Component<
  IGeminiChatProps,
  IGeminiChatState
> {
  private messagesEndRef = React.createRef<HTMLDivElement>()
  private textareaRef = React.createRef<HTMLTextAreaElement>()

  public constructor(props: IGeminiChatProps) {
    super(props)
    this.state = {
      messages: [],
      inputText: '',
      isLoading: false,
      selectedModel: getGeminiModel(),
      showModelSelector: false,
      error: null,
      pendingActions: [],
    }
  }

  public componentDidUpdate(
    _prevProps: IGeminiChatProps,
    prevState: IGeminiChatState
  ) {
    if (
      prevState.messages.length !== this.state.messages.length ||
      prevState.pendingActions.length !== this.state.pendingActions.length
    ) {
      this.scrollToBottom()
    }
  }

  private scrollToBottom() {
    this.messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  private onInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    this.setState({ inputText: e.target.value })
    // Auto-resize textarea
    const textarea = e.target
    textarea.style.height = 'auto'
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'
  }

  private onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      this.sendMessage()
    }
  }

  private sendMessage = async () => {
    const { inputText, messages, selectedModel, isLoading } = this.state

    if (!inputText.trim() || isLoading) {
      return
    }

    const userMessage: IChatMessage = {
      role: 'user',
      content: inputText.trim(),
      timestamp: Date.now(),
    }

    const updatedMessages = [...messages, userMessage]

    this.setState(
      {
        messages: updatedMessages,
        inputText: '',
        isLoading: true,
        error: null,
        pendingActions: [],
      },
      () => this.props.onMessagesChange?.()
    )

    // Reset textarea height
    if (this.textareaRef.current) {
      this.textareaRef.current.style.height = 'auto'
    }

    try {
      const apiKey = getGeminiApiKey()

      // Use agent message with function calling
      const agentResponse: IAgentResponse = await sendGeminiAgentMessage(
        updatedMessages,
        selectedModel,
        apiKey,
        this.props.repository,
        // Callback for each action executed
        (action: IAgentAction) => {
          this.setState(prevState => ({
            pendingActions: [...prevState.pendingActions, action],
          }))
        }
      )

      const assistantMessage: IChatMessage = {
        role: 'model',
        content: agentResponse.text,
        timestamp: Date.now(),
        actions:
          agentResponse.actions.length > 0
            ? agentResponse.actions
            : undefined,
      }

      this.setState(
        prevState => ({
          messages: [...prevState.messages, assistantMessage],
          isLoading: false,
          pendingActions: [],
        }),
        () => this.props.onMessagesChange?.()
      )
    } catch (error) {
      this.setState({
        isLoading: false,
        pendingActions: [],
        error:
          error instanceof Error ? error.message : 'An unknown error occurred',
      })
    }
  }

  private onModelChange = (model: GeminiModel) => {
    setGeminiModel(model)
    this.setState({ selectedModel: model, showModelSelector: false })
  }

  private toggleModelSelector = () => {
    this.setState(prevState => ({
      showModelSelector: !prevState.showModelSelector,
    }))
  }

  private onClearChat = () => {
    this.setState({ messages: [], error: null, pendingActions: [] }, () =>
      this.props.onMessagesChange?.()
    )
  }

  private getToolDisplayName(toolName: string): string {
    const nameMap: Record<string, string> = {
      git_status: 'Git Status',
      git_add: 'Git Add',
      git_commit: 'Git Commit',
      git_push: 'Git Push',
      git_pull: 'Git Pull',
      git_log: 'Git Log',
      git_diff: 'Git Diff',
      git_branch_list: 'Branch List',
      git_checkout: 'Git Checkout',
      git_create_branch: 'Create Branch',
      git_reset: 'Git Reset',
      git_stash: 'Git Stash',
      create_release_branch: 'Create Release Branch',
      generate_release_notes: 'Generate Release Notes',
      trigger_build: 'Trigger Build',
    }
    return nameMap[toolName] || toolName
  }

  private renderUserAvatar() {
    const { accounts } = this.props
    const account = accounts.length > 0 ? accounts[0] : undefined

    if (account) {
      const user = {
        email: account.emails.length > 0 ? account.emails[0].email : account.login,
        name: account.name || account.login,
        avatarURL: account.avatarURL,
        endpoint: account.endpoint,
      }
      return (
        <Avatar user={user} accounts={accounts} title={null} size={28} tooltip={false} />
      )
    }

    return '👤'
  }

  private renderActionBubble(action: IAgentAction, index: number) {
    const argsStr = Object.entries(action.args)
      .filter(([_, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
      .join(', ')

    return (
      <div
        key={`action-${index}`}
        className={`gemini-action-bubble ${
          action.success ? 'action-success' : 'action-error'
        }`}
      >
        <div className="action-header">
          <span className="action-icon">
            {action.success ? '⚡' : '❌'}
          </span>
          <span className="action-name">
            {this.getToolDisplayName(action.tool)}
          </span>
          {argsStr && (
            <span className="action-args">({argsStr})</span>
          )}
        </div>
        {action.result && (
          <div className="action-result">
            <pre>{action.result}</pre>
          </div>
        )}
      </div>
    )
  }

  private renderMessages() {
    const { messages, isLoading, pendingActions } = this.state

    return (
      <div className="gemini-chat-messages">
        {messages.map((msg, index) => (
          <React.Fragment key={index}>
            {/* Render action bubbles before the model message */}
            {msg.role === 'model' &&
              msg.actions &&
              msg.actions.map((action, actionIdx) =>
                this.renderActionBubble(action, actionIdx)
              )}
            <div
              className={`gemini-chat-bubble ${
                msg.role === 'user' ? 'user-bubble' : 'model-bubble'
              }`}
            >
              <div className="bubble-avatar">
                {msg.role === 'user'
                  ? this.renderUserAvatar()
                  : '✨'}
              </div>
              <div className="bubble-content">
                <div className="bubble-role">
                  {msg.role === 'user' ? 'You' : 'Gemini'}
                </div>
                <div className="bubble-text">{msg.content}</div>
              </div>
            </div>
          </React.Fragment>
        ))}
        {/* Show pending actions as they are being executed */}
        {pendingActions.map((action, index) =>
          this.renderActionBubble(action, index)
        )}
        {isLoading && (
          <div className="gemini-chat-bubble model-bubble">
            <div className="bubble-avatar">✨</div>
            <div className="bubble-content">
              <div className="bubble-role">Gemini</div>
              <div className="bubble-text loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={this.messagesEndRef} />
      </div>
    )
  }

  private renderError() {
    const { error } = this.state
    if (!error) {
      return null
    }

    return <div className="gemini-chat-error">⚠️ {error}</div>
  }

  private renderModelSelector() {
    const { showModelSelector, selectedModel } = this.state
    const models: GeminiModel[] = [
      'gemini-3-pro-preview',
      'gemini-3-flash-preview',
    ]

    return (
      <div className="gemini-model-selector-wrapper">
        <button
          className="gemini-model-selector-button"
          onClick={this.toggleModelSelector}
          title="Select model"
        >
          {getModelDisplayName(selectedModel)}
          <span className="dropdown-arrow">▾</span>
        </button>
        {showModelSelector && (
          <div className="gemini-model-dropdown">
            {models.map(model => (
              <button
                key={model}
                className={`gemini-model-option ${
                  model === selectedModel ? 'selected' : ''
                }`}
                onClick={() => this.onModelChange(model)}
              >
                {getModelDisplayName(model)}
                {model === selectedModel && (
                  <span className="check-mark">✓</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  private renderInputArea() {
    const { inputText, isLoading, messages } = this.state

    return (
      <div className="gemini-chat-input-area">
        <div className="gemini-chat-top-bar">
          {this.renderModelSelector()}
          {messages.length > 0 && (
            <button
              className="gemini-clear-button"
              onClick={this.onClearChat}
              title="Clear chat"
            >
              Clear chat
            </button>
          )}
        </div>
        <div className="gemini-chat-input-row">
          <textarea
            ref={this.textareaRef}
            className="gemini-chat-textarea"
            placeholder="Tell the agent what you want to do with version control..."
            value={inputText}
            onChange={this.onInputChange}
            onKeyDown={this.onKeyDown}
            disabled={isLoading}
            rows={2}
          />
          <button
            className="gemini-send-button"
            onClick={this.sendMessage}
            disabled={!inputText.trim() || isLoading}
            title="Send message"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="currentColor"
            >
              <path d="M1.724 1.053a.5.5 0 0 1 .545-.065l12 6a.5.5 0 0 1 0 .894l-12 6A.5.5 0 0 1 1.5 13.5v-4.379l6.854-1.143L1.5 6.835V2.5a.5.5 0 0 1 .224-.447z" />
            </svg>
          </button>
        </div>
      </div>
    )
  }

  /**
   * Returns true if there are chat messages to display
   */
  public hasMessages(): boolean {
    return this.state.messages.length > 0
  }

  public render() {
    const hasMessages = this.state.messages.length > 0

    return (
      <div
        className={`gemini-chat-panel ${
          hasMessages ? 'has-messages' : 'no-messages'
        }`}
      >
        {hasMessages && this.renderMessages()}
        {this.renderError()}
        {this.renderInputArea()}
      </div>
    )
  }
}
