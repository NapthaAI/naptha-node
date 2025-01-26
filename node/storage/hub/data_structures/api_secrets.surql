DEFINE TABLE api_secrets SCHEMAFULL;

DEFINE FIELD user_id ON api_secrets TYPE record<user>;
DEFINE FIELD secret_value ON api_secrets TYPE string;   
DEFINE FIELD key_name ON api_secrets TYPE string;

DEFINE FIELD created_at ON api_secrets TYPE datetime VALUE $before OR time::now() DEFAULT time::now();
DEFINE FIELD updated_at ON api_secrets TYPE datetime VALUE time::now() DEFAULT time::now();

DEFINE INDEX unique_key_secret ON api_secrets FIELDS key_name, secret_value UNIQUE;