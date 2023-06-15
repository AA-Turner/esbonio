// PYTHONPATH="$(pwd)/bundled/libs" python -S -c "import sys;print('\n'.join(sys.path))"
import * as vscode from 'vscode'

import { OutputChannelLogger } from '../common/log'
import { PythonManager } from './python'
import { EsbonioClient } from './client'

let esbonio: EsbonioClient
let logger: OutputChannelLogger

export async function activate(context: vscode.ExtensionContext) {
  let channel = vscode.window.createOutputChannel("Esbonio", "esbonio-log-output")
  let logLevel = vscode.workspace.getConfiguration('esbonio').get<string>('server.logLevel')

  logger = new OutputChannelLogger(channel, logLevel)

  let python = new PythonManager(logger)
  esbonio = new EsbonioClient(logger, python, context, channel)

  let config = vscode.workspace.getConfiguration("esbonio.server")
  if (config.get("enabled")) {
    await esbonio.start()
  }
}

export function deactivate(): Thenable<void> | undefined {
  if (!esbonio) {
    return undefined
  }
  return esbonio.stop()
}