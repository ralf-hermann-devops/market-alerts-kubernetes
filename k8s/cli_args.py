import argparse


SECRETS = (
    ("webhook_secret", "webhook-secret", "TradingView webhook secret"),
    ("redis_password", "redis-password", "Redis password"),
    ("postgres_password", "postgres-password", "PostgreSQL password"),
)


def create_parser(
    description: str = "Create a SealedSecret manifest.",
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--webhook-secret", help="TradingView webhook secret value")
    parser.add_argument("--redis-password", help="Redis password value")
    parser.add_argument("--postgres-password", help="PostgreSQL password value")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; fail unless all secrets are supplied",
    )
    return parser


def validate_secret_args(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    provided_secrets = {argument: getattr(args, argument) for argument, _, _ in SECRETS}
    if any(provided_secrets[argument] == "" for argument, _, _ in SECRETS):
        parser.error("secret values cannot be empty")

    missing_secrets = [
        option for argument, option, _ in SECRETS if provided_secrets[argument] is None
    ]
    if args.non_interactive and missing_secrets:
        parser.error(
            "non-interactive mode requires all secrets; missing "
            + ", ".join("--" + key for key in missing_secrets)
        )
