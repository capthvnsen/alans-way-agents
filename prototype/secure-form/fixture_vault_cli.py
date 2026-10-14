"""Offline public-CLI-shaped fixture, NOT Hermes and NOT encrypted storage.

Consumes password on stdin via getpass (detached, no TTY), discards it, then
acknowledges. No files, subprocesses, network, real credentials, or private imports.
"""
import getpass
import sys

if sys.argv[1:] != ['vault', 'add', '--kind', 'login']:
    sys.exit(2)
label = input("Label (e.g. 'GitHub work account'): ")
origin = input('Site origin (e.g. https://github.com): ')
kind = input('Identifier type (email/phone/username) [email]: ')
identifier = input('Username: ')
password = getpass.getpass('Password (hidden): ')
otp = getpass.getpass('Authenticator key (optional, hidden): ')
if not password or not label or not identifier or kind != 'username' or otp:
    sys.exit(1)
password = None
print(f'Stored. handle=vault_000000000000 kind=login origin={origin}')
