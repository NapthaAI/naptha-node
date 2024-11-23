import asyncio
import logging
import threading
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Dict, List, Optional, Union

from node.config import LOCAL_DB_URL
from node.storage.db.models import AgentRun, OrchestratorRun, EnvironmentRun, User
from node.schemas import (
    AgentRun as AgentRunSchema, 
    OrchestratorRun as OrchestratorRunSchema,
    EnvironmentRun as EnvironmentRunSchema,
    AgentRunInput,
    OrchestratorRunInput,
    EnvironmentRunInput
)

logger = logging.getLogger(__name__)

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
            LOCAL_DB_URL,
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

class DB:
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

    async def create_module_run(self, run_input: Union[Dict, any], run_type: str) -> Union[AgentRunSchema, OrchestratorRunSchema, EnvironmentRunSchema]:
        model_map = {
            'agent': (AgentRun, AgentRunSchema),
            'orchestrator': (OrchestratorRun, OrchestratorRunSchema),
            'environment': (EnvironmentRun, EnvironmentRunSchema)
        }
        
        try:
            Model, Schema = model_map[run_type]
            with self.session() as db:
                if hasattr(run_input, 'model_dump'):
                    run = Model(**run_input.model_dump())
                else:
                    run = Model(**run_input)
                db.add(run)
                db.flush()
                db.refresh(run)
                logger.info(f"Created {run_type} run: {run.__dict__}")
                return Schema(**run.__dict__)
        except SQLAlchemyError as e:
            logger.error(f"Failed to create {run_type} run: {str(e)}")
            raise

    async def create_agent_run(self, agent_run_input: Union[AgentRunInput, Dict]) -> AgentRunSchema:
        return await self.create_module_run(agent_run_input, 'agent')

    async def create_orchestrator_run(self, orchestrator_run_input: Union[OrchestratorRunInput, Dict]) -> OrchestratorRunSchema:
        return await self.create_module_run(orchestrator_run_input, 'orchestrator')

    async def create_environment_run(self, environment_run_input: Union[EnvironmentRunInput, Dict]) -> EnvironmentRunSchema:
        return await self.create_module_run(environment_run_input, 'environment')

    async def update_run(self, run_id: int, run_data: Union[AgentRunSchema, OrchestratorRunSchema, EnvironmentRunSchema], run_type: str) -> bool:
        model_map = {
            'agent': AgentRun,
            'orchestrator': OrchestratorRun,
            'environment': EnvironmentRun
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

    async def update_orchestrator_run(self, run_id: int, run_data: OrchestratorRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'orchestrator')

    async def update_environment_run(self, run_id: int, run_data: EnvironmentRunSchema) -> bool:
        return await self.update_run(run_id, run_data, 'environment')

    async def list_module_runs(self, run_type: str, run_id: Optional[int] = None) -> Union[Dict, List[Dict], None]:
        model_map = {
            'agent': AgentRun,
            'orchestrator': OrchestratorRun,
            'environment': EnvironmentRun
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

    # Replace existing list functions with these wrapper methods
    async def list_agent_runs(self, agent_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('agent', agent_run_id)

    async def list_orchestrator_runs(self, orchestrator_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('orchestrator', orchestrator_run_id)

    # Optional: Add environment runs support
    async def list_environment_runs(self, environment_run_id=None) -> Union[Dict, List[Dict], None]:
        return await self.list_module_runs('environment', environment_run_id)

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2)
    )
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