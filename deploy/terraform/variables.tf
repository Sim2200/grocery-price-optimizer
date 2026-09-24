variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "grocery-optimizer"
}

variable "environment" {
  description = "Environment name, e.g. dev or prod."
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "Address range of the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "kubernetes_version" {
  description = "EKS control plane version."
  type        = string
  default     = "1.31"
}

variable "node_instance_type" {
  description = "EC2 instance type of the EKS worker nodes."
  type        = string
  default     = "t3.medium"
}

variable "node_min_size" {
  description = "Minimum number of worker nodes."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum number of worker nodes."
  type        = number
  default     = 3
}

variable "node_desired_size" {
  description = "Number of worker nodes to start with."
  type        = number
  default     = 2
}

variable "db_instance_class" {
  description = "RDS instance class for Postgres."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Postgres storage in GB."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Name of the Postgres database the app uses."
  type        = string
  default     = "grocery"
}

variable "db_username" {
  description = "Postgres master user name. The password is generated and kept in Secrets Manager."
  type        = string
  default     = "grocery_admin"
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "deletion_protection" {
  description = "Protect the database from accidental deletion. Turn on for production."
  type        = bool
  default     = false
}
