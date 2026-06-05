output "ecr_repository_url" {
  description = "Push images here (docker tag + push)."
  value       = aws_ecr_repository.app.repository_url
}

output "app_url" {
  description = "Public HTTPS URL of the App Runner service."
  value       = "https://${aws_apprunner_service.app.service_url}"
}

output "apprunner_service_arn" {
  description = "App Runner service ARN (used by CI to trigger deployments)."
  value       = aws_apprunner_service.app.arn
}

output "rds_endpoint" {
  description = "Postgres endpoint (host:port)."
  value       = "${aws_db_instance.postgres.address}:5432"
}

output "database_secret_arn" {
  description = "Secrets Manager ARN holding the DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "aws_region" {
  value = var.aws_region
}
