import asyncio
from contextlib import contextmanager
from dotenv import load_dotenv
import json
import logging
import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
import threading
from typing import Dict, List, Optional, Union, Any

from node.storage.db.models import AgentRun, MemoryRun, OrchestratorRun, EnvironmentRun, User, KBRun, ToolRun
from node.schemas import (
    AgentRun as AgentRunSchema,
    MemoryRunInput,
    MemoryRun as MemoryRunSchema,
    OrchestratorRun as OrchestratorRunSchema,
    EnvironmentRun as EnvironmentRunSchema,
    AgentRunInput,
    OrchestratorRunInput,
    EnvironmentRunInput,
    KBRunInput,
    KBRun as KBRunSchema,
    ToolRunInput,
    ToolRun as ToolRunSchema
)

load_dotenv()
logger = logging.getLogger(__name__)

LOCAL_DB_POSTGRES_HOST = "pgvector" if os.getenv("LAUNCH_DOCKER") == "true" else "localhost"

class DatabasePool:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.engine = create_engine(
            f"postgresql://{os.getenv('LOCAL_DB_POSTGRES_USERNAME')}:{os.getenv('LOCAL_DB_POSTGRES_PASSWORD')}@{LOCAL_DB_POSTGRES_HOST}:{os.getenv('LOCAL_DB_POSTGRES_PORT')}/{os.getenv('LOCAL_DB_POSTGRES_NAME')}",
            poolclass=QueuePool,
            pool_size=120,          # Base pool size
            max_overflow=240,      # More overflow for 120 workers
            pool_timeout=30,
            pool_recycle=300,      # 5 minute recycle
            pool_pre_ping=True,
            echo=False,
            connect_args={
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
                'options': '-c statement_timeout=30000'  # 30 second timeout
            }
        )
        
        self.session_factory = scoped_session(
            sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
        )

        self._setup_engine_events()

    def _setup_engine_events(self):
        @event.listens_for(self.engine, 'checkout')
        def on_checkout(dbapi_conn, connection_rec, connection_proxy):
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute('SELECT 1')
                cursor.close()
            except Exception:
                logger.error("Connection verification failed")
                raise OperationalError("Invalid connection")

    def dispose(self):
        """Dispose the engine and all connections"""
        if hasattr(self, 'engine'):
            self.engine.dispose()

def clean_value_for_postgres(value):
    """Clean a value to make it PostgreSQL compatible"""
    if isinstance(value, str):
        # Remove NULL bytes and other problematic control characters
        return ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
    elif isinstance(value, dict):
        return {k: clean_value_for_postgres(v) for k, v in value.items()}
    elif isinstance(value, list):
        if any(isinstance(x, (int, float)) for x in value):  # Likely a vector
            return value
        return [clean_value_for_postgres(x) for x in value]
    return value

class LocalDBPostgres:
    def __init__(self):
        self.is_authenticated = False
        self.pool = DatabasePool()

    @contextmanager
    def session(self):
        session = self.pool.session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database error: {str(e)}")
            raise
        finally:
            session.close()
            self.pool.session_factory.remove()

    def get_pool_stats(self) -> Dict:
        return {
            'size': self.pool.engine.pool.size(),
            'checkedin': self.pool.engine.pool.checkedin(),
            'overflow': self.pool.engine.pool.overflow(),
            'checkedout': self.pool.engine.pool.checkedout(),
        }

    async def create_user(self, user_input: Dict) -> Dict:
        try:
            with self.session() as db:
                user = User(**user_input)
                db.add(user)
                db.flush()
                db.refresh(user)
                return user.__dict__
        except SQLAlchemyError as e:
            logger.error(f"Failed to create user: {str(e)}")
            raise

    async def get_user(self, user_input: Dict) -> Optional[Dict]:
        try:
            with self.session() as db:
                user = db.query(User).filter_by(public_key=user_input["public_key"]).first()
                return user.__dict__ if user else None
        except SQLAlchemyError as e:
            logger.error(f"Failed to get user: {str(e)}")
            raise

    async def get_public_key_by_id(self, user_id: str) -> Optional[Dict]:
        try:
            with self.session() as db:
                user = db.query(User).filter_by(id=user_id).first()
                return user.__dict__["public_key"] if user else None
        except SQLAlchemyError as e:
            logger.error(f"Failed to get user: {str(e)}")
            raise

    async def create_module_run(self, run_input: Union[Dict, any], run_type: str) -> Union[AgentRunSchema, MemoryRunSchema, OrchestratorRunSchema, EnvironmentRunSchema, ToolRunSchema]:
        model_map = {
            'agent': (AgentRun, AgentRunSchema),
            'memory': (MemoryRun, MemoryRunSchema),
            'orchestrator': (OrchestratorRun, OrchestratorRunSchema),
            'environment': (EnvironmentRun, EnvironmentRunSchema),
            'knowledge_base': (KBRun, KBRunSchema),
            'tool': (ToolRun, ToolRunSchema)
        }
        
        try:
            Model, Schema = model_map[run_type]
            with self.session() as db:
                if hasattr(run_input, 'model_dict'):
                    run = Model(**run_input.model_dict())
                else:
                    run = Model(**run_input)
                db.add(run)
                db.flush()
                db.refresh(run)
                logger.info(f"Created {run_type} run")
                logger.debug(f"{run_type} run: {run.__dict__}")
                return Schema(**run.__dict__)
        except SQLAlchemyError as e:
            logger.error(f"Failed to create {run_type} run: {str(e)}")
            raise

    async def create_agent_run(self, agent_run_input: Union[AgentRunInput, Dict]) -> AgentRunSchema:
        return await self.create_module_run(agent_run_input, 'agent')
    
    async def create_memory_run(self, memory_run_input: Union[MemoryRunInput, Dict]) -> MemoryRunSchema:
        return await self.create_module_run(memory_run_input, 'memory')

    async def create_tool_run(self, tool_run_input: Union[ToolRunInput, Dict]) -> ToolRunSchema:
        return await self.create_module_run(tool_run_input, 'tool')

    async def create_orchestrator_run(self, orchestrator_run_input: Union[OrchestratorRunInput, Dict]) -> OrchestratorRunSchema:
        return await self.create_module_run(orchestrator_run_input, 'orchestrator')

    async def create_environment_run(self, environment_run_input: Union[EnvironmentRunInput, Dict]) -> EnvironmentRunSchema:
        return await self.create_module_run(environment_run_input, 'environment')

    async def create_kb_run(self, kb_run_input: Union[KBRunInput, Dict]) -> KBRunSchema:
        return await self.create_module_run(kb_run_input, 'knowledge_base')

    async def update_run(self, run_id: int, run_data: Union[AgentRunSchema, MemoryRunSchema, OrchestratorRunSchema, EnvironmentRunSchema, ToolRunSchema], run_type: str) -> bool:
        model_map = {
            'agent': AgentRun,
            'memory': MemoryRun,
            'orchestrator': OrchestratorRun,
            'environment': EnvironmentRun,
            'knowledge_base': KBRun,
            'tool': ToolRun
        }
        
        try:
            Model = model_map[run_type]
            with self.session() as db:
                if hasattr(run_data, 'model_dump'):
                    run_data = run_data.model_dump()
                db_run = db.query(Model).filter(Model.id == run_id).first()
                if db_run:
                    for key, value in run_data.items():
                        setattr(db_run, key, value)
                    db.flush()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"Failed to update {run_type} run: {str(e)}")
            raise

    async def update_agent_run(self, run_id: int, run_data: AgentRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'agent')
    
    async def update_memory_run(self, run_id: int, run_data: MemoryRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'memory')

    async def update_tool_run(self, run_id: int, run_data: ToolRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'tool')

    async def update_orchestrator_run(self, run_id: int, run_data: OrchestratorRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'orchestrator')

    async def update_environment_run(self, run_id: int, run_data: EnvironmentRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'environment')
    
    async def update_kb_run(self, run_id: int, run_data: KBRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'knowledge_base')

    async def list_module_runs(self, run_type: str, run_id: Optional[int] = None) -> Union[Dict, List[Dict], None]:
        model_map = {
            'agent': AgentRun,
            'memory': MemoryRun,
            'orchestrator': OrchestratorRun,
            'environment': EnvironmentRun,
            'knowledge_base': KBRun,
            'tool': ToolRun
        }
        
        max_retries = 3
        retry_delay = 1  # seconds
        Model = model_map[run_type]
        
        for attempt in range(max_retries):
            try:
                with self.session() as db:
                    if run_id:
                        result = db.query(Model).filter(
                            Model.id == run_id
                        ).first()
                        if not result:
                            logger.warning(f"{run_type.capitalize()} run {run_id} not found on attempt {attempt + 1}")
                            await asyncio.sleep(retry_delay)
                            continue
                        return result.__dict__ if result else None
                    return [run.__dict__ for run in db.query(Model).all()]
            except SQLAlchemyError as e:
                logger.error(f"Database error on attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay)

    async def list_agent_runs(self, agent_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('agent', agent_run_id)
    
    async def list_memory_runs(self, memory_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('memory', memory_run_id)

    async def list_tool_runs(self, tool_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('tool', tool_run_id)

    async def list_orchestrator_runs(self, orchestrator_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('orchestrator', orchestrator_run_id)

    async def list_environment_runs(self, environment_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('environment', environment_run_id)

    async def list_kb_runs(self, kb_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('knowledge_base', kb_run_id)

    async def delete_agent_run(self, agent_run_id: int) -> bool:
        try:
            with self.session() as db:
                agent_run = db.query(AgentRun).filter(
                    AgentRun.id == agent_run_id
                ).first()
                if agent_run:
                    db.delete(agent_run)
                    db.flush()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"Failed to delete agent run: {str(e)}")
            raise

    async def delete_orchestrator_run(self, orchestrator_run_id: int) -> bool:
        try:
            with self.session() as db:
                orchestrator_run = db.query(OrchestratorRun).filter(
                    OrchestratorRun.id == orchestrator_run_id
                ).first()
                if orchestrator_run:
                    db.delete(orchestrator_run)
                    db.flush()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"Failed to delete orchestrator run: {str(e)}")
            raise

    async def query(self, query_str: str) -> List:
        try:
            with self.session() as db:
                result = db.execute(text(query_str))
                return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Failed to execute query: {str(e)}")
            raise

    def _get_sqlalchemy_type(self, pg_type: str, dimension: Optional[int] = None):
        """Convert PostgreSQL type to SQLAlchemy type"""
        from sqlalchemy import String, Integer, Float, Boolean, ARRAY, TIMESTAMP, JSON
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.types import TypeDecorator, UserDefinedType
        
        # Custom Vector type for PostgreSQL
        class Vector(UserDefinedType):
            def __init__(self, dimension=None):
                self.dimension = dimension

            def get_col_spec(self, **kw):
                if self.dimension is None:
                    raise ValueError("Vector dimension must be specified")
                return f"vector({self.dimension})"

            def bind_processor(self, dialect):
                def process(value):
                    if value is None:
                        return None
                    if not isinstance(value, list):
                        raise ValueError("Vector value must be a list of floats")
                    if len(value) != self.dimension:
                        raise ValueError(f"Vector must have exactly {self.dimension} dimensions")
                    return value
                return process

            def result_processor(self, dialect, coltype):
                def process(value):
                    if value is None:
                        return None
                    return value
                return process
        
        type_map = {
            'text': String,
            'integer': Integer,
            'float': Float,
            'boolean': Boolean,
            'jsonb': JSONB,
            'timestamp': TIMESTAMP,
            'vector': Vector
        }
        
        def create_type(type_str: str):
            """Helper function to create the appropriate SQLAlchemy type"""
            if type_str == 'vector':
                if dimension is None:
                    raise ValueError("Dimension must be specified for vector type")
                return Vector(dimension)
            elif type_str.endswith('[]'):
                base_type = type_str[:-2]
                if base_type not in type_map:
                    raise ValueError(f"Unsupported array type: {base_type}")
                return ARRAY(type_map[base_type]())
            else:
                return type_map[type_str]()

        return create_type(pg_type)

    async def create_dynamic_table(self, table_name: str, schema: Dict[str, Dict[str, Any]]) -> bool:
        """Create table dynamically using SQLAlchemy"""
        from sqlalchemy import MetaData, Table, Column
        try:
            metadata = MetaData()
            columns = []
            
            # Create pgvector extension if not exists
            with self.session() as db:
                db.execute(text('CREATE EXTENSION IF NOT EXISTS vector;'))
                db.commit()
            
            for field_name, properties in schema.items():
                # Convert type to lowercase
                field_type_str = properties['type'].lower()
                
                # Get the SQL type
                if field_type_str == 'vector':
                    dimension = properties.get('dimension')
                    if dimension is None:
                        raise ValueError(f"Dimension must be specified for vector field {field_name}")
                    field_type = self._get_sqlalchemy_type(field_type_str, dimension)
                else:
                    field_type = self._get_sqlalchemy_type(field_type_str)
                
                column_args = {
                    'primary_key': properties.get('primary_key', False),
                    'nullable': not properties.get('required', False)
                }
                
                if 'default' in properties:
                    column_args['default'] = properties['default']
                    
                columns.append(Column(field_name, field_type, **column_args))

            # Create the table
            Table(table_name, metadata, *columns)
            metadata.create_all(self.pool.engine)
            return True
                
        except Exception as e:
            logger.error(f"Failed to create table: {str(e)}")
            raise

    async def delete_dynamic_table(self, table_name: str) -> bool:
        """Delete a dynamically created table"""
        try:
            with self.session() as db:
                # Drop the table if it exists
                query = text(f"DROP TABLE IF EXISTS {table_name}")
                db.execute(query)
                db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete table: {str(e)}")
            raise

    async def add_dynamic_row(self, table_name: str, 
                            data: Union[Dict[str, Any], List[Dict[str, Any]]], 
                            schema: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        """Add one or multiple rows to dynamically created table"""
        try:
            # Convert single dict to list for consistent processing
            data_rows = [data] if isinstance(data, dict) else data
            
            if not data_rows:
                return True
                
            with self.session() as db:
                # Get column types once for all rows
                type_query = text("""
                    SELECT column_name, data_type, udt_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name
                """)
                result = db.execute(type_query, {"table_name": table_name})
                column_types = {row[0]: (row[1], row[2]) for row in result}

                # Process all rows
                processed_rows = []
                for row_data in data_rows:
                    # Clean the entire row data first
                    cleaned_row_data = clean_value_for_postgres(row_data)
                    
                    processed_data = {}
                    for key, value in cleaned_row_data.items():
                        if key in column_types:
                            data_type, udt_name = column_types[key]
                            
                            if udt_name == 'vector':
                                if not isinstance(value, list):
                                    raise ValueError(f"Vector field {key} must be a list")
                                processed_data[key] = value
                            elif data_type == 'jsonb':
                                processed_data[key] = json.dumps(value)
                            elif data_type.startswith('_'):
                                processed_data[key] = value
                            else:
                                processed_data[key] = value
                    processed_rows.append(processed_data)

                if not processed_rows:
                    return True

                # Get columns from the first row
                columns = list(processed_rows[0].keys())
                placeholders = [f":{col}" for col in columns]

                # Construct insert query
                query = text(f"""
                    INSERT INTO {table_name} 
                    ({', '.join(columns)}) 
                    VALUES 
                    ({', '.join(placeholders)})
                """)

                # Execute inserts
                if len(processed_rows) == 1:
                    # Single row insert
                    db.execute(query, processed_rows[0])
                else:
                    # Batch insert
                    db.execute(query, processed_rows)
                    
                return True

        except Exception as e:
            logger.error(f"Failed to add row(s): {str(e)}")
            logger.error(f"Input data: {data}")
            logger.error(f"Processed rows: {processed_rows if 'processed_rows' in locals() else 'Not processed'}")
            raise

    async def list_dynamic_rows(self, table_name: str, limit: Optional[int] = None, 
                              offset: Optional[int] = None) -> List[Dict[str, Any]]:
        """List rows from dynamically created table"""
        try:
            with self.session() as db:
                # Build query with optional limit and offset
                query = f"SELECT * FROM {table_name}"
                if limit is not None:
                    query += f" LIMIT {limit}"
                if offset is not None:
                    query += f" OFFSET {offset}"
                
                result = db.execute(text(query))
                
                # Convert rows to list of dicts
                columns = result.keys()
                rows = []
                for row in result:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        row_dict[col] = row[i]
                    rows.append(row_dict)
                    
                return rows

        except Exception as e:
            logger.error(f"Failed to list rows: {str(e)}")
            raise

    async def update_dynamic_row(self, table_name: str, data: Dict[str, Any],
                            condition: Dict[str, Any]) -> int:
        """Update rows in dynamically created table"""
        try:
            with self.session() as db:
                # Get schema information
                schema_query = text("""
                    SELECT column_name, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                """)
                result = db.execute(schema_query, {"table_name": table_name})
                column_types = {row[0]: (row[1], row[2]) for row in result}

                # Process the data based on column types
                processed_data = {}
                for key, value in data.items():
                    if key in column_types:
                        data_type, udt_name = column_types[key]
                        
                        if udt_name == 'vector':
                            if not isinstance(value, list):
                                raise ValueError(f"Vector field {key} must be a list")
                            processed_data[key] = value
                        elif data_type == 'jsonb':
                            processed_data[key] = json.dumps(value)
                        elif data_type.startswith('_'):
                            processed_data[key] = value
                        else:
                            processed_data[key] = value

                set_clause = ", ".join([f"{k} = :{k}" for k in processed_data.keys()])
                where_clause = " AND ".join([f"{k} = :condition_{k}" for k in condition.keys()])
                
                # Merge processed data and condition with prefixed condition keys
                params = {**processed_data, **{f"condition_{k}": v for k, v in condition.items()}}
                
                query = text(f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}")
                result = db.execute(query, params)
                return result.rowcount

        except Exception as e:
            logger.error(f"Failed to update row: {str(e)}")
            raise

    async def delete_dynamic_row(self, table_name: str, condition: Dict[str, Any]) -> int:
        """Delete rows from dynamically created table"""
        try:
            with self.session() as db:
                where_clause = " AND ".join([f"{k} = :{k}" for k in condition.keys()])
                query = text(f"DELETE FROM {table_name} WHERE {where_clause}")
                result = db.execute(query, condition)
                return result.rowcount
        except Exception as e:
            logger.error(f"Failed to delete row: {str(e)}")
            raise

    async def query_dynamic_table(
        self,
        table_name: str,
        columns: Optional[List[str]] = None,
        condition: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Query rows from a table"""
        try:
            with self.session() as db:
                select_clause = "*" if not columns else ", ".join(columns)
                query = f"SELECT {select_clause} FROM {table_name}"
                params = {}
                
                if condition:
                    where_clause = " AND ".join([f"{k} = :{k}" for k in condition.keys()])
                    query += f" WHERE {where_clause}"
                    params.update(condition)
                
                if order_by:
                    query += f" ORDER BY {order_by}"
                    
                if limit:
                    query += f" LIMIT {limit}"
                
                result = db.execute(text(query), params)
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Failed to query table: {str(e)}")
            raise

    async def vector_similarity_search(
        self,
        table_name: str,
        vector_column: str,
        query_vector: List[float],
        columns: List[str] = ["text"],
        top_k: int = 5,
        include_similarity: bool = True
    ) -> List[Dict[str, Any]]:
        vector_str = "[" + ",".join(str(x) for x in query_vector) + "]"
        # Inline the vector literal in the query to avoid ':qvec::vector' syntax issues
        vector_literal = f"'{vector_str}'::vector"

        select_items = columns[:]
        if include_similarity:
            select_items.append(f"{vector_column} <-> {vector_literal} AS distance")
        select_clause = ", ".join(select_items)

        query_str = f"""
            SELECT {select_clause}
            FROM {table_name}
            ORDER BY {vector_column} <-> {vector_literal}
            LIMIT :limit
        """

        with self.session() as db:
            result = db.execute(text(query_str), {"limit": top_k})
            return [dict(row._mapping) for row in result]

    async def list_dynamic_tables(self) -> List[str]:
        """Get list of all tables"""
        try:
            with self.session() as db:
                query = text("""
                    SELECT tablename 
                    FROM pg_catalog.pg_tables 
                    WHERE schemaname != 'pg_catalog' 
                    AND schemaname != 'information_schema'
                """)
                result = db.execute(query)
                return [row[0] for row in result]
        except Exception as e:
            logger.error(f"Failed to list tables: {str(e)}")
            raise

    async def get_dynamic_table_schema(self, table_name: str) -> Dict[str, Dict[str, Any]]:
        """Get schema information for a specific table without casting 'vector[]' to int."""
        try:
            with self.session() as db:
                query = text("""
                    SELECT 
                        column_name, 
                        data_type,
                        udt_name,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                """)

                result = db.execute(query, {"table_name": table_name})

                schema = {}
                for row in result:
                    # For a pgvector column, just store 'vector' as the type (no dimension parsing).
                    # 'udt_name' will often just be 'vector'.
                    col_type = row.udt_name if row.udt_name == 'vector' else row.data_type

                    schema[row.column_name] = {
                        "type": col_type,
                        "required": (row.is_nullable == 'NO'),
                        "default": row.column_default
                    }

                return schema
        except Exception as e:
            logger.error(f"Failed to get table schema: {str(e)}")
            raise


    async def check_connection_health(self) -> bool:
        try:
            with self.session() as session:
                session.execute(text("SELECT 1"))
                return True
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return False

    async def get_connection_stats(self) -> Dict:
        try:
            with self.session() as db:
                result = db.execute(text("""
                    SELECT count(*) as connection_count 
                    FROM pg_stat_activity 
                    WHERE datname = current_database()
                """))
                return dict(result.fetchone())
        except Exception as e:
            logger.error(f"Failed to get connection stats: {str(e)}")
            return {}

    async def connect(self):
        self.is_authenticated = await self.check_connection_health()
        return self.is_authenticated, None, None

    async def close(self):
        self.is_authenticated = False
        self.pool.dispose()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()