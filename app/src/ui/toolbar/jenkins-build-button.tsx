import * as React from 'react'
import { ToolbarButton } from './button'
import * as octicons from '../octicons/octicons.generated'
import { Dispatcher } from '../dispatcher'
import { PopupType } from '../../models/popup'
import { Repository } from '../../models/repository'

interface IJenkinsBuildButtonProps {
  readonly disabled?: boolean
  readonly branchName: string | null
  readonly repository: Repository
  readonly dispatcher: Dispatcher
}

export class JenkinsBuildButton extends React.Component<IJenkinsBuildButtonProps> {
  private onClick = () => {
    this.props.dispatcher.showPopup({
        type: PopupType.JenkinsBuild,
        repository: this.props.repository,
        initialBranch: this.props.branchName
    })
  }

  public render() {
    return (
      <ToolbarButton
        title="Jenkins"
        description="Last build unknown"
        icon={octicons.play} 
        onClick={this.onClick}
        disabled={this.props.disabled}
      />
    )
  }
}
