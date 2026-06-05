# Optional custom domain for the App Runner service.
#
# When `custom_domain` is set and its public hosted zone exists in Route 53 in
# this same AWS account, the AssociateCustomDomain call (made by the resource
# below) makes App Runner automatically create BOTH the ACM certificate
# validation records and the apex alias record in Route 53. The apex must use a
# Route 53 alias because a plain CNAME cannot point a zone apex at App Runner.
#
# Leave `custom_domain` empty to disable (default), so this file is a no-op until
# the domain is registered.

variable "custom_domain" {
  description = "Apex custom domain for the app (e.g. catalystbacktest.com). Empty disables it. The domain must be registered with its public hosted zone present in Route 53 in this account."
  type        = string
  default     = ""
}

resource "aws_apprunner_custom_domain_association" "app" {
  count = var.custom_domain == "" ? 0 : 1

  domain_name          = var.custom_domain
  service_arn          = aws_apprunner_service.app.arn
  enable_www_subdomain = true
}

# App Runner's auto-creation of Route 53 records only fires reliably from the
# console, so we manage them explicitly here for a reproducible setup.
data "aws_route53_zone" "this" {
  count        = var.custom_domain == "" ? 0 : 1
  name         = "${var.custom_domain}."
  private_zone = false
}

data "aws_apprunner_hosted_zone_id" "this" {}

# ACM certificate validation records (apex + www + service-level).
resource "aws_route53_record" "validation" {
  for_each = var.custom_domain == "" ? {} : {
    for r in aws_apprunner_custom_domain_association.app[0].certificate_validation_records : r.name => r
  }

  zone_id         = data.aws_route53_zone.this[0].zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.value]
  ttl             = 300
  allow_overwrite = true
}

# Apex must be an alias (a CNAME can't sit at the zone apex).
resource "aws_route53_record" "apex" {
  count = var.custom_domain == "" ? 0 : 1

  zone_id = data.aws_route53_zone.this[0].zone_id
  name    = var.custom_domain
  type    = "A"

  alias {
    name                   = aws_apprunner_custom_domain_association.app[0].dns_target
    zone_id                = data.aws_apprunner_hosted_zone_id.this.id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "www" {
  count = var.custom_domain == "" ? 0 : 1

  zone_id = data.aws_route53_zone.this[0].zone_id
  name    = "www.${var.custom_domain}"
  type    = "A"

  alias {
    name                   = aws_apprunner_custom_domain_association.app[0].dns_target
    zone_id                = data.aws_apprunner_hosted_zone_id.this.id
    evaluate_target_health = true
  }
}

output "custom_domain_url" {
  description = "Public HTTPS URL on the custom domain (null until configured)."
  value       = var.custom_domain == "" ? null : "https://${var.custom_domain}"
}

output "custom_domain_dns_target" {
  description = "App Runner DNS target the custom domain points at."
  value       = var.custom_domain == "" ? null : aws_apprunner_custom_domain_association.app[0].dns_target
}

output "custom_domain_validation_records" {
  description = "ACM certificate validation records (App Runner auto-creates these in Route 53 for same-account zones; shown here for manual setup if needed)."
  value       = var.custom_domain == "" ? null : aws_apprunner_custom_domain_association.app[0].certificate_validation_records
}
