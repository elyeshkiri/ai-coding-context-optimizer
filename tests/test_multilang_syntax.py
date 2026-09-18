from token_saver.repo_index import record_for_text
from token_saver.snippet import extract_symbol
from token_saver.syntax import symbols


def _qualified(text: str, suffix: str) -> set[str]:
    return {item.qualified for item in symbols(text, suffix)}


def test_go_extracts_receiver_methods_and_types():
    source = """package api

type Engine struct {
    name string
}

func NewEngine() *Engine {
    return &Engine{}
}

func (e *Engine) ServeHTTP() {
    e.dispatch()
}

func (e Engine) Run() error {
    return e.listen()
}
"""
    names = _qualified(source, ".go")
    assert {"Engine", "NewEngine", "Engine.ServeHTTP", "Engine.Run"} <= names

    record = record_for_text("engine.go", source)
    definitions = {item.name: item for item in record.definitions or []}
    assert definitions["ServeHTTP"].parent == "Engine"
    assert definitions["ServeHTTP"].kind == "method"
    assert "dispatch" in (definitions["ServeHTTP"].calls or [])
    assert "ServeHTTP" in record.symbols


def test_rust_extracts_impl_and_trait_methods():
    source = """pub struct Json<T>(pub T);

impl<T> Json<T> {
    pub fn into_response(self) -> String {
        self.render()
    }
}

pub trait Handler {
    fn call(&self);
}
"""
    names = _qualified(source, ".rs")
    assert {"Json", "Json.into_response", "Handler", "Handler.call"} <= names

    record = record_for_text("json.rs", source)
    defs = {(item.parent, item.name): item for item in record.definitions or []}
    assert defs[("Json", "into_response")].kind == "method"
    assert "render" in (defs[("Json", "into_response")].calls or [])
    assert defs[("Handler", "call")].kind == "method"


def test_java_extracts_classes_interfaces_constructors_and_methods():
    source = """package demo;

public class Service {
    public Service() {}

    public void run() {
        helper();
    }
}

interface Handler {
    void handle();
}
"""
    names = _qualified(source, ".java")
    assert {
        "Service",
        "Service.Service",
        "Service.run",
        "Handler",
        "Handler.handle",
    } <= names

    record = record_for_text("Service.java", source)
    defs = {(item.parent, item.name): item for item in record.definitions or []}
    assert defs[("Service", "run")].kind == "method"
    assert "helper" in (defs[("Service", "run")].calls or [])


def test_csharp_extracts_types_methods_constructors_and_properties():
    source = """namespace Demo {
    public class Controller {
        public Controller() {}

        public string Name { get; set; }

        public void Run() {
            Execute();
        }
    }

    public interface IHandler {
        void Handle();
    }
}
"""
    names = _qualified(source, ".cs")
    assert {
        "Controller",
        "Controller.Controller",
        "Controller.Name",
        "Controller.Run",
        "IHandler",
        "IHandler.Handle",
    } <= names

    record = record_for_text("Controller.cs", source)
    defs = {(item.parent, item.name): item for item in record.definitions or []}
    assert defs[("Controller", "Name")].kind == "property"
    assert defs[("Controller", "Run")].kind == "method"
    assert "Execute" in (defs[("Controller", "Run")].calls or [])


def test_structured_signatures_drop_large_bodies():
    go = """package p

type Service struct {
    Alpha string
    Beta string
}

func (s *Service) Run() {
    first()
    second()
    third()
}
"""
    items = {item.qualified: item for item in symbols(go, ".go")}
    assert "Alpha string" not in items["Service"].signature
    assert "first()" not in items["Service.Run"].signature
    assert "Run" in items["Service.Run"].signature


def test_snippet_uses_exact_go_method_boundaries():
    source = """package api

func (e *Engine) Run() {
    first()
    second()
}

func Other() {}
"""
    result = extract_symbol(source, ".go", "Engine.Run")
    assert result is not None
    snippet, start, end = result
    assert start == 3
    assert end == 6
    assert "first()" in snippet
    assert "func Other" not in snippet
    assert "approximate boundaries" not in snippet
