DEFINE TABLE persona SCHEMAFULL 
   PERMISSIONS
       FOR select, create WHERE $session.ac = 'user'
       FOR update, delete WHERE author = $auth.id;

DEFINE FIELD name ON TABLE persona TYPE string;
DEFINE FIELD description ON TABLE persona TYPE string;
DEFINE FIELD parameters ON TABLE persona TYPE string;
DEFINE FIELD author ON TABLE persona TYPE record<user>;
DEFINE FIELD module_url ON TABLE persona TYPE string;
DEFINE FIELD module_type ON TABLE persona TYPE string;
DEFINE FIELD module_version ON TABLE persona TYPE string;
DEFINE FIELD module_entrypoint ON TABLE persona TYPE option<string>;