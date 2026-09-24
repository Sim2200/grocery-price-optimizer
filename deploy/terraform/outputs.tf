output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "configure_kubectl" {
  description = "Command that adds the cluster to your kubeconfig."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "postgres_endpoint" {
  description = "RDS host:port."
  value       = aws_db_instance.postgres.endpoint
}

output "postgres_password_secret_arn" {
  description = "Secrets Manager secret holding the generated Postgres master password."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "database_url_template" {
  description = "DATABASE_URL for the app; fill in the password from the secret above."
  value       = "postgresql+psycopg://${var.db_username}:<password>@${aws_db_instance.postgres.endpoint}/${var.db_name}"
}

output "redis_endpoint" {
  description = "ElastiCache primary endpoint (TLS on port 6379)."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}
