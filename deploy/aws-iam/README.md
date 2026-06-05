# GitHub OIDC deploy role for AWS

These two policies let the [deploy workflow](../../.github/workflows/deploy.yml)
authenticate to AWS via GitHub OIDC (no long-lived keys) and push images +
trigger App Runner deployments.

- [github-oidc-trust-policy.json](github-oidc-trust-policy.json) - *who* can assume
  the role: only this repo's `main` branch, via GitHub's OIDC provider.
- [deploy-permissions-policy.json](deploy-permissions-policy.json) - *what* the role
  may do: ECR login/push to the `catalyst-backtester` repo and
  `apprunner:StartDeployment` on the service.

## Placeholders to replace
- `ACCOUNT_ID` - your 12-digit AWS account id.
- `REGION` - e.g. `us-east-1` (must match `var.aws_region`).
- The repo slug `liyifan5923013/catalyst-backtester` is already filled in; change it
  if you fork. To allow more than just `main`, change the trust `sub` to
  `repo:OWNER/REPO:*`.

## One-time setup (copy-paste)

```bash
cd deploy/aws-iam

export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGION=us-east-1

# 1. Create the GitHub OIDC identity provider (skip if it already exists).
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  2>/dev/null || echo "OIDC provider already exists, continuing"

# 2. Fill placeholders into local copies of the policies.
sed -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" -e "s/REGION/$REGION/g" \
  github-oidc-trust-policy.json > /tmp/trust.json
sed -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" -e "s/REGION/$REGION/g" \
  deploy-permissions-policy.json > /tmp/perms.json

# 3. Create the role and attach the inline permissions.
aws iam create-role \
  --role-name catalyst-gha-deploy \
  --assume-role-policy-document file:///tmp/trust.json

aws iam put-role-policy \
  --role-name catalyst-gha-deploy \
  --policy-name catalyst-deploy \
  --policy-document file:///tmp/perms.json

# 4. Print the ARN to paste into the GitHub repo secret AWS_DEPLOY_ROLE_ARN.
aws iam get-role --role-name catalyst-gha-deploy --query Role.Arn --output text
```

> The thumbprint above is GitHub's well-known OIDC CA thumbprint. AWS now
> validates OIDC against its trust store, but the field is still required by the
> API; if your account already has the provider, step 1 is a no-op.

## Then, in the GitHub repo (Settings -> Secrets and variables -> Actions)
- Secret `AWS_DEPLOY_ROLE_ARN` = the ARN printed by step 4.
- Variables `AWS_REGION`, `ECR_REPOSITORY` (`catalyst-backtester`),
  `APPRUNNER_SERVICE_ARN` (`tofu output apprunner_service_arn`).

Push to `main` and the pipeline builds, pushes, and deploys.
