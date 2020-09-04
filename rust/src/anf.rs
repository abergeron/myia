extern crate generational_arena;

use self::generational_arena::{Arena, Index};
use std::collections::HashSet;
use std::cell::*;

#[derive(Copy, Clone)]
pub enum Value<'a> {
    Graph(GraphPtr<'a>),
    // Other types later
}

struct Graph<'a> {
    parameters: Vec<ANFNodePtr<'a>>,
    return_: Option<ANFNodePtr<'a>>,
    //debug:
    //flags:
    //transforms: HashMap<String, GraphPtr>,
}

#[derive(Copy, Clone)]
pub struct GraphPtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>,
}

impl<'a> GraphPtr<'a> {
    unsafe fn get(&self) -> Ref<Graph<'a>> {
        // Still unsafe as we return a sub-ref
        self.manager.get_graph(self.p).borrow()
    }

    unsafe fn get_mut(&self) -> RefMut<Graph<'a>> {
        // Still unsafe as we return a sub-ref
        self.manager.get_graph(self.p).borrow_mut()
    }

    pub fn get_output(&self) -> Option<ANFNodePtr<'a>> {
        unsafe {
            // This is safe because we don't keep the ref
            self.get().return_
        }
    }

    pub fn set_output(&self, out: ANFNodePtr<'a>) -> () {
        // We will see about having an Apply here.
        unsafe {
            // This is safe because we don't keep the ref
            self.get_mut().return_ = Some(out);
        }
    }

    pub fn add_parameter(&self) -> ANFNodePtr<'a> {
        let newp = self.manager.alloc_param(*self);
        unsafe {
            // This is safe because we don't keep the ref
            self.get_mut().parameters.push(newp);
        }
        newp
    }
}

#[derive(Clone)]
enum ANFNodeType<'a> {
    Apply(Vec<ANFNodePtr<'a>>),
    Parameter,
    Constant(Value<'a>),
}

struct ANFNode<'a> {
    node: ANFNodeType<'a>,
    graph: Option<GraphPtr<'a>>,
}

pub struct ANFNodeInputIter<'a> {
    vals: Vec<ANFNodePtr<'a>>,
    p: usize,
}

impl<'a> ANFNodeInputIter<'a> {
    fn new(node: Ref<'a, ANFNode<'a>>) -> Self {
        // SAFETY: Make sure that no ref to the passed-in node is kept
        ANFNodeInputIter {
            vals: match &node.node {
                ANFNodeType::Apply(inps) => inps.clone(),
                _ => Vec::new(),
            },
            p: 0,
        }
    }
}

impl<'a> Iterator for ANFNodeInputIter<'a> {
    type Item = ANFNodePtr<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        let elem = self.vals.get(self.p);
        self.p += 1;
        if let Some(v) = elem {
            Some(*v)
        } else {
            None
        }
    }
}

#[derive(Copy, Clone)]
pub struct ANFNodePtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>,
}

impl<'a> ANFNodePtr<'a> {
    unsafe fn get(&self) -> Ref<ANFNode<'a>> {
        // Still unsafe as we return a sub-ref
        self.manager.get_node(self.p).borrow()
    }

    pub fn incoming(&'a self) -> ANFNodeInputIter<'a> {
        unsafe {
            // This is safe because ANFNodeInputIter doesn't keep a ref
            ANFNodeInputIter::new(self.get())
        }
    }

    pub fn value(&'a self) -> Option<Value<'a>> {
        // This is safe because we don't keep the ref
        let n = unsafe { &self.get().node };
        match n {
            ANFNodeType::Constant(v) => Some(*v),
            _ => None,
        }
    }

    // Maybe value matching later, if needed
    pub fn is_apply(&self) -> bool {
        matches!(unsafe { &self.get().node }, ANFNodeType::Apply(_))
    }

    pub fn is_parameter(&self) -> bool {
        matches!(unsafe { &self.get().node }, ANFNodeType::Parameter)
    }

    // Some way to check for type later, if needed
    pub fn is_constant(&self) -> bool {
        matches!(unsafe { &self.get().node }, ANFNodeType::Constant(_))
    }

    pub fn is_constant_graph(&self) -> bool {
        matches!(unsafe { &self.get().node }, ANFNodeType::Constant(Value::Graph(_)))
    }
}

pub struct GraphManager<'a> {
    roots: HashSet<ANFNodePtr<'a>>,
    all_nodes: Cell<Arena<RefCell<ANFNode<'a>>>>,
    graphs: Cell<Arena<RefCell<Graph<'a>>>>,
}

impl<'a> GraphManager<'a> {
    pub fn new() -> Self {
        GraphManager {
            roots: HashSet::<ANFNodePtr<'a>>::new(),
            all_nodes: Cell::new(Arena::new()),
            graphs: Cell::new(Arena::new()),
        }
    }

    // You can't allocate new graphs while the returned reference is alive
    unsafe fn get_graph(&self, p: Index) -> &RefCell<Graph<'a>> {
        (*self.graphs.as_ptr()).get(p).unwrap()
    }

    // You can't allocate new nodes while the returned reference is alive
    unsafe fn get_node(&self, p: Index) -> &RefCell<ANFNode<'a>> {
        (*self.all_nodes.as_ptr()).get(p).unwrap()
    }

    pub fn new_graph(&'a self) -> GraphPtr<'a> {
        let p = Vec::new();
        // This method is safe becase we don't return the ref
        let gs = unsafe { &mut *self.graphs.as_ptr() };
        let g = gs.insert(RefCell::new(Graph {
                parameters: p,
                return_: None,
        }));
        GraphPtr { p: g, manager: self }
    }

    pub fn alloc_apply(&'a self, params: Vec<ANFNodePtr<'a>>, graph: Option<GraphPtr<'a>>) -> ANFNodePtr<'a> {
        let n = ANFNodeType::Apply(params);
        // This method is safe becase we don't return the ref
        let an = unsafe { &mut *self.all_nodes.as_ptr() };
        let a = an.insert(RefCell::new(ANFNode {
            node: n,
            graph: graph,
        }));
        ANFNodePtr { p: a, manager: self }
    }

    fn alloc_param(&'a self, graph: GraphPtr<'a>) -> ANFNodePtr<'a> {
        // This method is safe becase we don't return the ref
        let an = unsafe { &mut *self.all_nodes.as_ptr() };
        let a = an.insert(RefCell::new(ANFNode {
            node: ANFNodeType::Parameter,
            graph: Some(graph),
        }));
        ANFNodePtr { p: a, manager: self }
    }
}
