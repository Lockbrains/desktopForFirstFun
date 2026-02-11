import * as React from 'react'
import { Dialog, DialogContent, DialogFooter } from '../dialog'
import { OkCancelButtonGroup } from '../dialog/ok-cancel-button-group'
import { Repository } from '../../models/repository'
import { Select } from '../lib/select'
import { TextBox } from '../lib/text-box'
import { Checkbox, CheckboxValue } from '../lib/checkbox'
import { PasswordTextBox } from '../lib/password-text-box'
import * as https from 'https'
import * as http from 'http'
import { URL } from 'url'

interface IJenkinsBuildDialogProps {
  readonly repository: Repository
  readonly initialBranch: string | null
  readonly onDismissed: () => void
}

interface IJenkinsBuildDialogState {
  readonly selectedPipeline: string
  readonly buildType: string
  readonly branch: string
  readonly installType: string // iOS only
  readonly tableEnv: string
  readonly simulateOnline: boolean
  readonly packAll: boolean
  readonly clearCache: boolean
  readonly debugHotUpdate: boolean
  readonly isSubmitting: boolean
  readonly jenkinsUser: string
  readonly jenkinsToken: string
}

const Pipelines = {
  'StarFire-Android-Debug-Pipeline': { platform: 'Android', defaultBuildType: 'APK' },
  'StarFire-Android-Release': { platform: 'Android', defaultBuildType: 'APK' },
  'StarFire-iOS-Debug-Pipeline': { platform: 'iOS', defaultBuildType: 'App' },
  'StarFire-iOS-Release-Pipeline': { platform: 'iOS', defaultBuildType: 'App' },
}

interface IRequestOptions extends http.RequestOptions {
    body?: string
}

export class JenkinsBuildDialog extends React.Component<
  IJenkinsBuildDialogProps,
  IJenkinsBuildDialogState
> {
  public constructor(props: IJenkinsBuildDialogProps) {
    super(props)
    
    // Default to first pipeline
    const initialPipeline = 'StarFire-Android-Debug-Pipeline'
    
    this.state = {
      selectedPipeline: initialPipeline,
      buildType: 'APK',
      branch: props.initialBranch || 'main',
      installType: 'Adhoc',
      tableEnv: 'dev',
      simulateOnline: false,
      packAll: false,
      clearCache: false,
      debugHotUpdate: true, // Default true for debug
      isSubmitting: false,
      jenkinsUser: localStorage.getItem('jenkins-user') || '',
      jenkinsToken: localStorage.getItem('jenkins-token') || '',
    }
  }

  private onPipelineChanged = (event: React.FormEvent<HTMLSelectElement>) => {
    const pipeline = event.currentTarget.value
    const config = Pipelines[pipeline as keyof typeof Pipelines]
    
    // Reset defaults based on pipeline
    const isDebug = pipeline.includes('Debug')
    const isIOS = config.platform === 'iOS'
    
    this.setState({
      selectedPipeline: pipeline,
      buildType: isIOS ? 'App' : 'APK',
      tableEnv: isDebug ? 'dev' : 'test',
      debugHotUpdate: isDebug,
      // Keep branch as is
    })
  }

  private onBuildTypeChanged = (event: React.FormEvent<HTMLSelectElement>) => {
    this.setState({ buildType: event.currentTarget.value })
  }

  private onInstallTypeChanged = (event: React.FormEvent<HTMLSelectElement>) => {
    this.setState({ installType: event.currentTarget.value })
  }

  private onBranchChanged = (branch: string) => {
    this.setState({ branch })
  }

  private onTableEnvChanged = (tableEnv: string) => {
    this.setState({ tableEnv })
  }

  private onSimulateOnlineChanged = (event: React.FormEvent<HTMLInputElement>) => {
    this.setState({ simulateOnline: event.currentTarget.checked })
  }

  private onPackAllChanged = (event: React.FormEvent<HTMLInputElement>) => {
    this.setState({ packAll: event.currentTarget.checked })
  }

  private onClearCacheChanged = (event: React.FormEvent<HTMLInputElement>) => {
    this.setState({ clearCache: event.currentTarget.checked })
  }

  private onDebugHotUpdateChanged = (event: React.FormEvent<HTMLInputElement>) => {
    this.setState({ debugHotUpdate: event.currentTarget.checked })
  }

  private onJenkinsUserChanged = (jenkinsUser: string) => {
      this.setState({ jenkinsUser })
  }

  private onJenkinsTokenChanged = (jenkinsToken: string) => {
      this.setState({ jenkinsToken })
  }

  private getAuthHeaders = (): Record<string, string> => {
      const { jenkinsUser, jenkinsToken } = this.state
      const headers: Record<string, string> = {}
      if (jenkinsUser && jenkinsToken) {
          headers['Authorization'] = 'Basic ' + Buffer.from(`${jenkinsUser}:${jenkinsToken}`).toString('base64')
      }
      return headers
  }

  private httpRequest = (urlStr: string, options: IRequestOptions): Promise<{ statusCode: number, headers: http.IncomingHttpHeaders, body: string }> => {
      return new Promise((resolve, reject) => {
          const url = new URL(urlStr)
          const client = url.protocol === 'https:' ? https : http
          const reqOptions = {
              hostname: url.hostname,
              port: url.port || (url.protocol === 'https:' ? 443 : 80),
              path: url.pathname + url.search,
              method: options.method || 'GET',
              headers: options.headers
          }

          console.log(`Node HTTP Request: ${reqOptions.method} ${urlStr}`, reqOptions.headers)

          const req = client.request(reqOptions, (res) => {
              let data = ''
              res.on('data', (chunk) => {
                  data += chunk
              })
              res.on('end', () => {
                  resolve({
                      statusCode: res.statusCode || 0,
                      headers: res.headers,
                      body: data
                  })
              })
          })

          req.on('error', (e) => {
              reject(e)
          })

          if (options.body) {
              req.write(options.body)
          }
          req.end()
      })
  }

  private onSubmit = async () => {
    const { selectedPipeline, buildType, branch, installType, tableEnv, simulateOnline, packAll, clearCache, debugHotUpdate, jenkinsUser, jenkinsToken } = this.state
    
    this.setState({ isSubmitting: true })

    // Save creds
    if (jenkinsUser) localStorage.setItem('jenkins-user', jenkinsUser)
    if (jenkinsToken) localStorage.setItem('jenkins-token', jenkinsToken)

    const baseHost = 'http://192.168.50.249:8080'
    const authHeaders = this.getAuthHeaders()

    try {
        // 1. Fetch Crumb using Node HTTP
        let crumbHeader: Record<string, string> = {}
        let cookieHeader: string | undefined = undefined

        try {
            console.log('Fetching crumb (Node HTTP)...')
            const crumbResp = await this.httpRequest(`${baseHost}/crumbIssuer/api/json`, {
                headers: authHeaders
            })

            console.log('Crumb response:', crumbResp.statusCode, crumbResp.headers)

            if (crumbResp.statusCode === 200) {
                const crumbData = JSON.parse(crumbResp.body)
                if (crumbData.crumb && crumbData.crumbRequestField) {
                    crumbHeader = { [crumbData.crumbRequestField]: crumbData.crumb }
                }
                
                // Capture Set-Cookie
                if (crumbResp.headers['set-cookie']) {
                    cookieHeader = crumbResp.headers['set-cookie'].map(c => c.split(';')[0]).join('; ')
                    console.log('Captured Cookies:', cookieHeader)
                }
            } else {
                console.warn('Failed to fetch crumb', crumbResp.statusCode, crumbResp.body)
            }
        } catch (e) {
            console.warn('Error fetching crumb', e)
        }

        // 2. Trigger Build using Node HTTP
        const baseUrl = `${baseHost}/job/${selectedPipeline}/buildWithParameters`
        const params = new URLSearchParams()
        
        params.append('BuildType', buildType)
        params.append('BRANCH', branch)
        params.append('TABLE_ENV', tableEnv)
        params.append('SIMULATE_ONLINE', simulateOnline.toString())
        params.append('PACK_ALL', packAll.toString())
        params.append('CLEAR_CACHE', clearCache.toString())
        params.append('USE_DEBUG_HOT_UPDATE', debugHotUpdate.toString())
        
        const config = Pipelines[selectedPipeline as keyof typeof Pipelines]
        if (config.platform === 'iOS') {
            params.append('InstallType', installType)
        }

        const buildUrl = `${baseUrl}?${params.toString()}`
        
        const buildHeaders = {
            ...authHeaders,
            ...crumbHeader
        }

        if (cookieHeader) {
            buildHeaders['Cookie'] = cookieHeader
        }

        console.log('Triggering build with headers:', buildHeaders)

        const response = await this.httpRequest(buildUrl, {
            method: 'POST',
            headers: buildHeaders
        })

        if (response.statusCode >= 200 && response.statusCode < 300) {
            this.props.onDismissed()
            alert(`Successfully triggered build for ${selectedPipeline}`)
        } else {
            console.error(`Failed: ${response.statusCode} ${response.body}`)
            alert(`Failed to trigger build: ${response.statusCode}\n${response.body}`)
            this.setState({ isSubmitting: false })
        }
    } catch (e) {
      console.error(e)
      alert(`Error: ${e}`)
      this.setState({ isSubmitting: false })
    }
  }

  public render() {
    const config = Pipelines[this.state.selectedPipeline as keyof typeof Pipelines]
    const isIOS = config.platform === 'iOS'
    const isDebug = this.state.selectedPipeline.includes('Debug')

    return (
      <Dialog
        id="jenkins-build"
        title="Build Pipeline"
        onSubmit={this.onSubmit}
        onDismissed={this.props.onDismissed}
        loading={this.state.isSubmitting}
      >
        <DialogContent>
            <div className="jenkins-build-row">
                <label>Pipeline</label>
                <Select value={this.state.selectedPipeline} onChange={this.onPipelineChanged}>
                    {Object.keys(Pipelines).map(p => <option key={p} value={p}>{p}</option>)}
                </Select>
            </div>

            <div className="jenkins-build-row">
                <label>Build Type</label>
                <Select value={this.state.buildType} onChange={this.onBuildTypeChanged}>
                    {isIOS 
                        ? <><option value="App">App</option><option value="HotUpdate">HotUpdate</option></>
                        : <><option value="APK">APK</option><option value="HotUpdate">HotUpdate</option></>
                    }
                </Select>
            </div>

            {isIOS && (
                <div className="jenkins-build-row">
                    <label>Install Type</label>
                    <Select value={this.state.installType} onChange={this.onInstallTypeChanged}>
                        <option value="Adhoc">Adhoc</option>
                        <option value="Xcode">Xcode</option>
                        {!isDebug && <option value="TestFlight">TestFlight</option>}
                    </Select>
                </div>
            )}

            <div className="jenkins-build-row">
                <label>Branch</label>
                <TextBox value={this.state.branch} onValueChanged={this.onBranchChanged} />
            </div>

            <div className="jenkins-build-row">
                <label>Table Env</label>
                <TextBox value={this.state.tableEnv} onValueChanged={this.onTableEnvChanged} />
            </div>

            <div className="jenkins-build-row">
                <label>Jenkins User (Optional)</label>
                <TextBox value={this.state.jenkinsUser} onValueChanged={this.onJenkinsUserChanged} placeholder="Username" />
            </div>

            <div className="jenkins-build-row">
                <label>Jenkins Token/Password (Optional)</label>
                <PasswordTextBox value={this.state.jenkinsToken} onValueChanged={this.onJenkinsTokenChanged} placeholder="API Token or Password" />
            </div>

            <div className="jenkins-build-checkboxes">
                <Checkbox 
                    label="Simulate Online" 
                    value={this.state.simulateOnline ? CheckboxValue.On : CheckboxValue.Off}
                    onChange={this.onSimulateOnlineChanged}
                />
                <Checkbox 
                    label="Pack All" 
                    value={this.state.packAll ? CheckboxValue.On : CheckboxValue.Off}
                    onChange={this.onPackAllChanged}
                />
                <Checkbox 
                    label="Clear Cache" 
                    value={this.state.clearCache ? CheckboxValue.On : CheckboxValue.Off}
                    onChange={this.onClearCacheChanged}
                />
                <Checkbox 
                    label="Debug Hot Update" 
                    value={this.state.debugHotUpdate ? CheckboxValue.On : CheckboxValue.Off}
                    onChange={this.onDebugHotUpdateChanged}
                />
            </div>
        </DialogContent>
        <DialogFooter>
            <OkCancelButtonGroup
              okButtonText="Build"
              onCancelButtonClick={this.props.onDismissed}
            />
        </DialogFooter>
      </Dialog>
    )
  }
}
