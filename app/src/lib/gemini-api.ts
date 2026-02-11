/**
 * Gemini API service for chat functionality.
 * Supports Gemini 3 Pro and Gemini 3 Flash models.
 * Includes function calling for agent capabilities.
 */

import { Repository } from '../models/repository'
import {
  agentToolDeclarations,
  executeAgentTool,
  IAgentAction,
} from './agent-tools'
import { getAgentSystemPrompt } from './agent-system-prompt'

export type GeminiModel = 'gemini-3-pro-preview' | 'gemini-3-flash-preview'

export interface IChatMessage {
  readonly role: 'user' | 'model'
  readonly content: string
  readonly timestamp: number
  /** Actions executed by the agent for this response (only on model messages) */
  readonly actions?: ReadonlyArray<IAgentAction>
}

interface IGeminiPart {
  text?: string
  functionCall?: {
    name: string
    args: Record<string, any>
  }
  functionResponse?: {
    name: string
    response: { content: string }
  }
  /** Gemini 3 models include thought signatures with function calls */
  thoughtSignature?: string
  [key: string]: any // Allow additional fields from the API
}

interface IGeminiContent {
  role: string
  parts: IGeminiPart[]
}

const GEMINI_API_BASE =
  'https://generativelanguage.googleapis.com/v1beta/models'

// ── LocalStorage helpers ──────────────────────────────────────────────

/**
 * Get the stored Gemini API key from localStorage
 */
export function getGeminiApiKey(): string {
  return localStorage.getItem('gemini-api-key') || ''
}

/**
 * Store the Gemini API key in localStorage
 */
export function setGeminiApiKey(key: string): void {
  localStorage.setItem('gemini-api-key', key)
}

/**
 * Get the stored model preference from localStorage
 */
export function getGeminiModel(): GeminiModel {
  const stored = localStorage.getItem('gemini-chat-model')
  if (
    stored === 'gemini-3-pro-preview' ||
    stored === 'gemini-3-flash-preview'
  ) {
    return stored
  }
  return 'gemini-3-pro-preview'
}

/**
 * Store the model preference in localStorage
 */
export function setGeminiModel(model: GeminiModel): void {
  localStorage.setItem('gemini-chat-model', model)
}

/**
 * Get the display name of a Gemini model
 */
export function getModelDisplayName(model: GeminiModel): string {
  switch (model) {
    case 'gemini-3-pro-preview':
      return 'Gemini 3 Pro'
    case 'gemini-3-flash-preview':
      return 'Gemini 3 Flash'
  }
}

/**
 * Get the stored context length from localStorage.
 * This controls how many messages (user + model turns) to include.
 */
export function getContextLength(): number {
  const stored = localStorage.getItem('gemini-context-length')
  if (stored) {
    const parsed = parseInt(stored, 10)
    if (!isNaN(parsed) && parsed > 0) {
      return parsed
    }
  }
  return 20 // default: 20 messages = ~10 exchanges
}

/**
 * Store the context length in localStorage
 */
export function setContextLength(length: number): void {
  localStorage.setItem('gemini-context-length', String(length))
}

// ── Simple chat (no agent) ────────────────────────────────────────────

/**
 * Send a chat message to the Gemini API and get a response.
 * This is the simple version without function calling.
 *
 * @param messages The conversation history
 * @param model The model to use
 * @param apiKey The API key
 * @param systemPrompt Optional system instruction
 * @returns The model's response text
 */
export async function sendGeminiMessage(
  messages: ReadonlyArray<IChatMessage>,
  model: GeminiModel,
  apiKey: string,
  systemPrompt?: string
): Promise<string> {
  if (!apiKey) {
    throw new Error(
      'Gemini API Key not configured. Please set your API key in the Release & AI > Settings panel.'
    )
  }

  const contents: IGeminiContent[] = messages.map(msg => ({
    role: msg.role === 'user' ? 'user' : 'model',
    parts: [{ text: msg.content }],
  }))

  const body: any = {
    contents,
    generationConfig: {
      temperature: 1.0,
      topP: 0.95,
      maxOutputTokens: 8192,
    },
  }

  if (systemPrompt) {
    body.system_instruction = {
      parts: [{ text: systemPrompt }],
    }
  }

  const url = `${GEMINI_API_BASE}/${model}:generateContent?key=${apiKey}`

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errorText = await response.text()
    let errorMessage = `API request failed (${response.status})`
    try {
      const errorJson = JSON.parse(errorText)
      if (errorJson.error?.message) {
        errorMessage = errorJson.error.message
      }
    } catch {
      // use default error message
    }
    throw new Error(errorMessage)
  }

  const data = await response.json()
  const text =
    data.candidates?.[0]?.content?.parts?.[0]?.text ||
    'No response generated.'
  return text
}

// ── Agent chat (with function calling) ────────────────────────────────

/** Result from the agent message flow */
export interface IAgentResponse {
  /** The final text response from the model */
  readonly text: string
  /** All actions executed during this turn */
  readonly actions: ReadonlyArray<IAgentAction>
}

/**
 * Send a message to the Gemini agent with function calling support.
 * Handles the full agent loop: send → function call → execute → respond → repeat.
 *
 * @param messages The conversation history (for context)
 * @param model The model to use
 * @param apiKey The API key
 * @param repository The current repository (for executing git commands)
 * @param onActionExecuted Optional callback fired when an action is executed
 * @returns The agent response including text and executed actions
 */
export async function sendGeminiAgentMessage(
  messages: ReadonlyArray<IChatMessage>,
  model: GeminiModel,
  apiKey: string,
  repository: Repository,
  onActionExecuted?: (action: IAgentAction) => void
): Promise<IAgentResponse> {
  if (!apiKey) {
    throw new Error(
      'Gemini API Key not configured. Please set your API key in the Release & AI > Settings panel.'
    )
  }

  const systemPrompt = getAgentSystemPrompt()

  // Build context from previous messages, respecting context length
  const contextLength = getContextLength()
  const contextMessages = messages.slice(-contextLength)

  // Build the initial API contents from message history
  const contents: IGeminiContent[] = contextMessages.map(msg => ({
    role: msg.role === 'user' ? 'user' : 'model',
    parts: [{ text: msg.content }],
  }))

  const allActions: IAgentAction[] = []
  const MAX_FUNCTION_CALL_LOOPS = 10 // safety limit

  for (let loop = 0; loop < MAX_FUNCTION_CALL_LOOPS; loop++) {
    const body: any = {
      contents,
      tools: [{ functionDeclarations: agentToolDeclarations }],
      generationConfig: {
        temperature: 1.0,
        topP: 0.95,
        maxOutputTokens: 8192,
      },
      system_instruction: {
        parts: [{ text: systemPrompt }],
      },
    }

    const url = `${GEMINI_API_BASE}/${model}:generateContent?key=${apiKey}`

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorText = await response.text()
      let errorMessage = `API request failed (${response.status})`
      try {
        const errorJson = JSON.parse(errorText)
        if (errorJson.error?.message) {
          errorMessage = errorJson.error.message
        }
      } catch {
        // use default
      }
      throw new Error(errorMessage)
    }

    const data = await response.json()
    const candidate = data.candidates?.[0]
    if (!candidate?.content?.parts) {
      return {
        text: 'No response generated.',
        actions: allActions,
      }
    }

    // Keep the raw parts from the API response to preserve
    // thoughtSignature and any other metadata fields
    const rawParts: any[] = candidate.content.parts
    const parts: IGeminiPart[] = rawParts

    // Check if the model wants to call a function
    const functionCallPart = parts.find(
      (p: IGeminiPart) => p.functionCall !== undefined
    )

    if (functionCallPart?.functionCall) {
      const { name, args } = functionCallPart.functionCall

      // Execute the tool
      let resultStr: string
      let success: boolean
      try {
        resultStr = await executeAgentTool(name, args || {}, repository)
        success = !resultStr.startsWith('Error')
      } catch (error) {
        resultStr =
          error instanceof Error ? error.message : String(error)
        success = false
      }

      const action: IAgentAction = {
        tool: name,
        args: args || {},
        result: resultStr,
        success,
      }
      allActions.push(action)
      onActionExecuted?.(action)

      // IMPORTANT: Add the model's ORIGINAL content (including
      // thoughtSignature) back to the conversation. Do NOT
      // reconstruct the parts — Gemini 3 requires thought
      // signatures to be preserved in function call parts.
      contents.push({
        role: 'model',
        parts: rawParts,
      })

      // Add the function response to contents
      contents.push({
        role: 'function' as string,
        parts: [
          {
            functionResponse: {
              name,
              response: { content: resultStr },
            },
          },
        ],
      })

      // Continue the loop to get the model's next response
      continue
    }

    // No function call - extract text response
    const textParts = parts
      .filter((p: IGeminiPart) => p.text !== undefined)
      .map((p: IGeminiPart) => p.text!)
    const fullText = textParts.join('') || 'No response generated.'

    return {
      text: fullText,
      actions: allActions,
    }
  }

  // Exceeded max loops
  return {
    text: 'The agent completed multiple actions. Please review the results above.',
    actions: allActions,
  }
}
