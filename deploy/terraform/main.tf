data "aws_caller_identity" "current" {}

# Use the account's default VPC + subnets to keep the module self-contained.
# For production, replace these with your own VPC/subnet module.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  # Only the VPC's original default subnets (public, with an IGW route). This
  # excludes the private subnets we create below, which also live in this VPC.
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Per-subnet detail so we can exclude AZs that App Runner does not support.
data "aws_subnet" "default" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
}

locals {
  name = var.project

  # App Runner VPC connectors are not available in every AZ (e.g. use1-az3 in
  # us-east-1). Keep only default (public) subnets in supported AZs.
  supported_subnets = [
    for s in data.aws_subnet.default : s
    if !contains(var.apprunner_unsupported_az_ids, s.availability_zone_id)
  ]

  # Public subnet (default VPC, has an Internet Gateway route) to host the NAT
  # instance, and the supported AZs we will place private subnets in.
  nat_public_subnet_id = local.supported_subnets[0].id
  private_azs          = slice(distinct([for s in local.supported_subnets : s.availability_zone]), 0, 2)

  # The App Runner connector lives in the private subnets (internet via NAT).
  connector_subnets = aws_subnet.private[*].id
}

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------
resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ---------------------------------------------------------------------------
# Networking: App Runner (egress) and RDS (ingress) security groups
# ---------------------------------------------------------------------------
resource "aws_security_group" "apprunner" {
  name        = "${local.name}-apprunner"
  description = "App Runner VPC connector egress"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "Postgres access from App Runner only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from App Runner"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.apprunner.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# RDS Postgres
# ---------------------------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  multi_az                = false
  skip_final_snapshot     = true
  deletion_protection     = false
  backup_retention_period = 7
  apply_immediately       = true
}

locals {
  database_url = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${var.db_name}"
}

# ---------------------------------------------------------------------------
# Secrets Manager: full DATABASE_URL injected into App Runner at runtime
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name}/database-url"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

# Optional: OpenAI-compatible API key for LLM summaries. Only created when a
# key is supplied; otherwise the app falls back to the rule-based summary.
resource "aws_secretsmanager_secret" "openai" {
  count = var.openai_api_key == "" ? 0 : 1
  name  = "${local.name}/openai-api-key"
}

resource "aws_secretsmanager_secret_version" "openai" {
  count         = var.openai_api_key == "" ? 0 : 1
  secret_id     = aws_secretsmanager_secret.openai[0].id
  secret_string = var.openai_api_key
}

# Optional: Alpha Vantage key for US equity fallback (Yahoo is primary).
resource "aws_secretsmanager_secret" "alpha_vantage" {
  count = var.alpha_vantage_api_key == "" ? 0 : 1
  name  = "${local.name}/alpha-vantage-api-key"
}

resource "aws_secretsmanager_secret_version" "alpha_vantage" {
  count         = var.alpha_vantage_api_key == "" ? 0 : 1
  secret_id     = aws_secretsmanager_secret.alpha_vantage[0].id
  secret_string = var.alpha_vantage_api_key
}

# ---------------------------------------------------------------------------
# IAM: App Runner ECR-pull (access) role and runtime (instance) role
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "apprunner_build_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_access" {
  name               = "${local.name}-apprunner-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_build_assume.json
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

data "aws_iam_policy_document" "apprunner_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${local.name}-apprunner-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_tasks_assume.json
}

data "aws_iam_policy_document" "apprunner_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.database_url.arn],
      var.openai_api_key == "" ? [] : [aws_secretsmanager_secret.openai[0].arn],
      var.alpha_vantage_api_key == "" ? [] : [aws_secretsmanager_secret.alpha_vantage[0].arn],
    )
  }
}

resource "aws_iam_role_policy" "apprunner_secrets" {
  name   = "${local.name}-read-db-secret"
  role   = aws_iam_role.apprunner_instance.id
  policy = data.aws_iam_policy_document.apprunner_secrets.json
}

# ---------------------------------------------------------------------------
# Egress: a small NAT instance so the App Runner connector (in private subnets)
# can reach the internet (Binance/Hyperliquid) while still reaching RDS in-VPC.
# A t4g.nano NAT instance is ~10x cheaper than a managed NAT Gateway.
# ---------------------------------------------------------------------------
data "aws_ami" "nat" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

resource "aws_subnet" "private" {
  count             = length(local.private_azs)
  vpc_id            = data.aws_vpc.default.id
  availability_zone = local.private_azs[count.index]
  cidr_block        = cidrsubnet("172.31.192.0/18", 6, count.index)

  tags = {
    Name = "${local.name}-private-${count.index}"
  }
}

resource "aws_security_group" "nat" {
  name        = "${local.name}-nat"
  description = "NAT instance: forward traffic from private subnets to the internet"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "All traffic from within the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "nat" {
  ami                         = data.aws_ami.nat.id
  instance_type               = "t4g.nano"
  subnet_id                   = local.nat_public_subnet_id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.nat.id]
  source_dest_check           = false

  user_data                   = file("${path.module}/nat-user-data.sh")
  user_data_replace_on_change = true

  tags = {
    Name = "${local.name}-nat"
  }
}

resource "aws_route_table" "private" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_instance.nat.primary_network_interface_id
  }

  tags = {
    Name = "${local.name}-private"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# App Runner: VPC connector (private subnets) + the service
# ---------------------------------------------------------------------------
# App Runner rejects a new connector whose security-group set exactly matches an
# existing connector's. This secondary SG keeps the set distinct so connector
# swaps (create_before_destroy) succeed.
resource "aws_security_group" "connector_extra" {
  name        = "${local.name}-connector-extra"
  description = "Secondary SG to keep the App Runner connector SG-set unique"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_apprunner_vpc_connector" "main" {
  # Name embeds a hash of the subnets so changing them creates a new connector
  # (App Runner connectors are immutable) before the old one is removed.
  vpc_connector_name = "${local.name}-vpc-${substr(sha1(join(",", local.connector_subnets)), 0, 6)}"
  subnets            = local.connector_subnets
  security_groups    = [aws_security_group.apprunner.id, aws_security_group.connector_extra.id]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_apprunner_service" "app" {
  service_name = local.name

  source_configuration {
    auto_deployments_enabled = true

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port = var.app_port

        runtime_environment_variables = {
          OPENAI_MODEL                = var.openai_model
          OPENAI_BASE_URL             = var.openai_base_url
          PREWARM_ENABLED             = var.prewarm_enabled ? "1" : "0"
          PREWARM_INTERVAL_HOURS      = tostring(var.prewarm_interval_hours)
          PREWARM_INTERVAL_MINUTES    = tostring(var.prewarm_interval_minutes)
          PREWARM_SOURCE_MIN_INTERVAL = jsonencode(var.prewarm_source_min_interval)
        }

        runtime_environment_secrets = merge(
          { DATABASE_URL = aws_secretsmanager_secret.database_url.arn },
          var.openai_api_key == "" ? {} : { OPENAI_API_KEY = aws_secretsmanager_secret.openai[0].arn },
          var.alpha_vantage_api_key == "" ? {} : { ALPHA_VANTAGE_API_KEY = aws_secretsmanager_secret.alpha_vantage[0].arn },
        )
      }
    }
  }

  instance_configuration {
    cpu               = var.apprunner_cpu
    memory            = var.apprunner_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.main.arn
    }
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/api/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  depends_on = [aws_secretsmanager_secret_version.database_url]
}
