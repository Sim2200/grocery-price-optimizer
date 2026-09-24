# Minimal AWS footprint for the app:
#   VPC (public + private + database + cache subnets)
#   EKS cluster with one managed node group     -> runs the Helm chart
#   RDS Postgres                                -> DATABASE_URL for the app
#   ElastiCache Redis                           -> a cache (not used by the app yet)
#
# Plan only: `terraform plan` shows what would be created. Nothing here has been applied.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.project}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

# ----- network --------------------------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets      = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnets     = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 10)]
  database_subnets    = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 20)]
  elasticache_subnets = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 30)]

  # One NAT gateway keeps cost down; use one per AZ for production.
  enable_nat_gateway = true
  single_nat_gateway = true

  create_database_subnet_group    = true
  create_elasticache_subnet_group = true

  # Tags the AWS load balancer controller uses to find subnets for load balancers.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

# ----- Kubernetes (EKS) ----------------------------------------------------------------

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = local.name
  cluster_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Reachable with kubectl from your machine; restrict or disable for production.
  cluster_endpoint_public_access           = true
  enable_cluster_creator_admin_permissions = true

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      min_size       = var.node_min_size
      max_size       = var.node_max_size
      desired_size   = var.node_desired_size
    }
  }
}

# ----- Postgres (RDS) -----------------------------------------------------------------

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Postgres, reachable only from the EKS worker nodes"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "Postgres from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name}-postgres"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username

  # RDS generates the password and stores it in Secrets Manager, so it never appears
  # in this code or in the Terraform state.
  manage_master_user_password = true

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period = 7
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = !var.deletion_protection
}

# ----- Redis (ElastiCache) ----------------------------------------------------------------

resource "aws_security_group" "redis" {
  name        = "${local.name}-redis"
  description = "Redis, reachable only from the EKS worker nodes"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "Redis from EKS nodes"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${local.name}-redis"
  description          = "Cache for ${local.name}"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = 1
  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name  = module.vpc.elasticache_subnet_group_name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}
