"""Provision a wend-agent ECS task and return its tunnel URL once ready."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

import boto3

from .clerk_client import UserMetadata
from .config import WendAgentConfig
from .github_app import mint_installation_token_for_install

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentHandle:
    agent_id: str
    tunnel_url: str
    task_arn: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _expires_at(idle_sec: int) -> int:
    return int(time.time()) + idle_sec


async def provision(
    cfg: WendAgentConfig,
    user_id: str,
    user_meta: UserMetadata,
    repo: str,
    ref: str,
    note_id: str | None,
) -> AgentHandle:
    agent_id = str(uuid.uuid4())
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    ssm = boto3.client("ssm", region_name=cfg.aws_region)
    ecs = boto3.client("ecs", region_name=cfg.aws_region)

    ddb.put_item(
        TableName=cfg.table_name,
        Item={
            "agentId": {"S": agent_id},
            "userId": {"S": user_id},
            "repo": {"S": repo},
            "ref": {"S": ref},
            "noteId": {"S": note_id or ""},
            "status": {"S": "PROVISIONING"},
            "createdAt": {"S": _now_iso()},
            "expiresAt": {"N": str(_expires_at(cfg.idle_timeout_sec))},
        },
    )

    assert user_meta.github_installation_id is not None, "github install required pre-provision"
    assert user_meta.anthropic_api_key, "anthropic api key required pre-provision"
    install = await mint_installation_token_for_install(
        cfg, user_meta.github_installation_id, repo,
    )
    token_param = f"/wend/agents/{agent_id}/github_token"
    anth_param = f"/wend/agents/{agent_id}/anthropic_key"

    ssm.put_parameter(Name=token_param, Value=install.token, Type="SecureString", Overwrite=True)
    ssm.put_parameter(Name=anth_param, Value=user_meta.anthropic_api_key, Type="SecureString", Overwrite=True)

    overrides = {
        "containerOverrides": [{
            "name": "wend-agent",
            "environment": [
                {"name": "WEND_AGENT_ID", "value": agent_id},
                {"name": "WEND_REPO", "value": repo},
                {"name": "WEND_REPO_REF", "value": ref},
            ],
            "secrets": [
                {"name": "WEND_GITHUB_INSTALL_TOKEN", "valueFrom": token_param},
                {"name": "WEND_ANTHROPIC_API_KEY", "valueFrom": anth_param},
            ],
        }]
    }

    resp = ecs.run_task(
        cluster=cfg.cluster_name,
        taskDefinition=cfg.task_definition_arn,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": cfg.subnet_ids,
                "securityGroups": [cfg.security_group_id],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides=overrides,
        propagateTags="TASK_DEFINITION",
    )
    if resp.get("failures"):
        logger.error("ecs run_task failures: %s", resp["failures"])
        raise RuntimeError(f"ecs run_task failed: {resp['failures']}")
    task_arn = resp["tasks"][0]["taskArn"]

    ddb.update_item(
        TableName=cfg.table_name,
        Key={"agentId": {"S": agent_id}},
        UpdateExpression="SET taskArn = :t, #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":t": {"S": task_arn}, ":s": {"S": "STARTING"}},
    )

    tunnel_url = await _await_tunnel(ddb, cfg, agent_id, timeout_sec=90)
    return AgentHandle(agent_id=agent_id, tunnel_url=tunnel_url, task_arn=task_arn)


async def _await_tunnel(ddb, cfg: WendAgentConfig, agent_id: str, *, timeout_sec: int) -> str:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        item = ddb.get_item(TableName=cfg.table_name, Key={"agentId": {"S": agent_id}}).get("Item", {})
        url = item.get("tunnelUrl", {}).get("S")
        if url:
            return url
        await asyncio.sleep(2.0)
    raise TimeoutError(f"agent {agent_id} never published a tunnel URL")
