"""Replace sandbox image login, build, and push steps in sandbox-runner.yaml."""

from __future__ import annotations

import argparse
import subprocess

from tools.ci.gha import repo_root, required_env

ACTOR = "ACTOR"
BUILD = "build"
DESCRIPTION = "Build and publish the sandbox runner image."
DOCKER = "docker"
DOCKERFILE = "docker/sandbox-runner/Dockerfile"
GITHUB_SHA = "GITHUB_SHA"
GITHUB_TOKEN = "GITHUB_TOKEN"
IMAGE_NAME = "IMAGE_NAME"
LATEST = "latest"
LOGIN = "login"
PASSWORD_STDIN = "--password-stdin"
PUSH = "push"
REGISTRY = "ghcr.io"
TAG = "-t"
USER = "-u"


def docker(arguments: list[str], *, input_text: str | None = None) -> None:
    """Run Docker because no project helper or native API owns these operations."""
    subprocess.run([DOCKER, *arguments], check=True, input=input_text, text=True, cwd=repo_root())


def main(argv: list[str] | None = None) -> int:
    """Authenticate, build both image tags, then push both tags."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    image_name = required_env(IMAGE_NAME)
    actor = required_env(ACTOR)
    token = required_env(GITHUB_TOKEN)
    sha = required_env(GITHUB_SHA)
    tagged_image = image_name + ":" + sha
    latest_image = image_name + ":" + LATEST
    # Docker login's password-stdin protocol avoids exposing the token in argv.
    docker([LOGIN, REGISTRY, USER, actor, PASSWORD_STDIN], input_text=token + "\n")
    # Docker builds the OCI image format required by the registry publish path.
    docker([BUILD, TAG, tagged_image, TAG, latest_image, "-f", DOCKERFILE, "."])
    # Docker owns registry push semantics for the image tags produced above.
    docker([PUSH, tagged_image])
    docker([PUSH, latest_image])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
