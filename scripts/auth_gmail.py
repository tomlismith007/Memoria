"""Interactive Gmail OAuth bootstrapping script.

Usage:
    python scripts/auth_gmail.py [--credentials data/credentials.json] [--token data/token.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from memoria.mail.auth import get_gmail_credentials, get_gmail_service


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Authenticate with Gmail OAuth")
    parser.add_argument(
        "--credentials",
        default="data/credentials.json",
        help="Path to credentials.json downloaded from Google Cloud Console",
    )
    parser.add_argument(
        "--token",
        default="data/token.json",
        help="Path where token.json will be saved",
    )
    args = parser.parse_args()

    cred_path = Path(args.credentials)
    token_path = Path(args.token)

    print("=" * 60)
    print("Memoria - Gmail API OAuth 授权助手")
    print("=" * 60)

    if not cred_path.exists():
        print(f"\n[提示] 未找到 OAuth 凭据文件: {cred_path}")
        print("\n请按以下步骤获取凭据：")
        print("1. 前往 Google Cloud Console: https://console.cloud.google.com/")
        print("2. 启用 Gmail API (APIs & Services -> Enable APIs and Services)")
        print("3. 创建凭据: Credentials -> Create Credentials -> OAuth client ID")
        print("   - Application type 选择 'Desktop app'")
        print("4. 下载客户端密钥 JSON 文件，保存到本地:")
        print(f"   -> {cred_path.resolve()}")
        print("\n完成后重新运行本脚本即可！")
        return 1

    print(f"\n[OK] 找到凭据文件: {cred_path}")
    print("正在启动本地浏览器完成授权...")

    try:
        creds = get_gmail_credentials(cred_path, token_path)
        if creds:
            print(f"[OK] 授权成功！Token 已落盘至: {token_path}")
            # Test ping
            service = get_gmail_service(cred_path, token_path)
            profile = service.users().getProfile(userId="me").execute()
            print(f"[OK] 已连接邮箱: {profile.get('emailAddress')}")
            print("现在启动 python run_web.py 即可实时拉取分拣真实邮件！")
            return 0
    except Exception as e:
        print(f"[错误] 授权失败: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
