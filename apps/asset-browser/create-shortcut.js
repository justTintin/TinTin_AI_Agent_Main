const { exec } = require('child_process');
const path = require('path');
const os = require('os');

function createShortcut() {
  const projectDir = __dirname;
  const batPath = path.join(projectDir, '启动.bat');
  const desktopDir = path.join(os.homedir(), 'Desktop');
  const shortcutPath = path.join(desktopDir, '螺丝钉-电商智能体矩阵 素材浏览器.lnk');
  
  // PowerShell 脚本内容，用于创建指向 启动.bat 的快捷方式
  const psScript = `
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut("${shortcutPath}")
$Shortcut.TargetPath = "${batPath}"
$Shortcut.WorkingDirectory = "${projectDir}"
$Shortcut.WindowStyle = 7
$Shortcut.Description = "启动 螺丝钉-电商智能体矩阵 素材浏览器"
$Shortcut.Save()
  `.trim();

  // 将 PowerShell 脚本转换为 UTF-16LE 编码的 Base64，以防止任何字符集和转义引发的解析问题
  const buffer = Buffer.from(psScript, 'utf16le');
  const base64 = buffer.toString('base64');
  
  exec(`powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${base64}`, (err) => {
    if (err) {
      console.error('创建桌面快捷方式失败:', err);
    } else {
      console.log('桌面快捷方式已成功创建到您的 Windows 桌面！');
    }
  });
}

createShortcut();
