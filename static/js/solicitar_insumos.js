let insumosSeleccionados = [];
let todosInsumos = [];

function inicializarInsumos(insumosData) {
    todosInsumos = insumosData;
}

document.getElementById('buscarInsumo').addEventListener('input', function() {
    const termino = this.value.toLowerCase();
    if (termino.length > 2) {
        mostrarInsumosFiltrados(termino);
    }
});

function mostrarInsumosFiltrados(termino) {
    const resultados = todosInsumos.filter(i => 
        i.nombre.toLowerCase().includes(termino) || 
        i.codigo.toLowerCase().includes(termino)
    ).slice(0, 10);
    
    const lista = document.getElementById('listaInsumos');
    lista.innerHTML = '';
    
    if (resultados.length === 0) {
        lista.innerHTML = '<div class="list-group-item">No se encontraron insumos</div>';
        return;
    }
    
    resultados.forEach(insumo => {
        const item = document.createElement('div');
        item.className = 'list-group-item list-group-item-action';
        item.innerHTML = `
            <div class="d-flex w-100 justify-content-between">
                <h6 class="mb-1">${insumo.codigo} - ${insumo.nombre}</h6>
                <small>Stock: ${insumo.stock_actual} ${insumo.unidad}</small>
            </div>
        `;
        item.onclick = () => seleccionarInsumo(insumo);
        lista.appendChild(item);
    });
    
    new bootstrap.Modal(document.getElementById('modalInsumos')).show();
}

function seleccionarInsumo(insumo) {
    const existe = insumosSeleccionados.find(i => i.id === insumo.id);
    if (existe) {
        alert('✅ Este insumo ya está agregado');
        return;
    }
    
    const nuevo = {
        id: insumo.id,
        codigo: insumo.codigo,
        nombre: insumo.nombre,
        cantidad: 1,
        stock_actual: insumo.stock_actual,
        unidad: insumo.unidad
    };
    
    insumosSeleccionados.push(nuevo);
    actualizarTabla();
    document.getElementById('buscarInsumo').value = '';
    bootstrap.Modal.getInstance(document.getElementById('modalInsumos')).hide();
}

function actualizarTabla() {
    const tbody = document.querySelector('#tablaSolicitados tbody');
    tbody.innerHTML = '';
    
    let totalItems = 0;
    insumosSeleccionados.forEach((insumo, index) => {
        totalItems++;
        const stockDisponible = insumo.stock_actual - insumo.cantidad;
        const fila = `
            <tr>
                <td>${insumo.codigo}</td>
                <td>${insumo.nombre}</td>
                <td>
                    <input type="number" class="form-control form-control-sm" 
                           value="${insumo.cantidad}" min="1" max="${insumo.stock_actual}"
                           onchange="actualizarCantidad(${index}, this.value)">
                </td>
                <td><span class="badge ${stockDisponible > 0 ? 'bg-success' : 'bg-danger'}">
                    ${stockDisponible} ${insumo.unidad}
                </span></td>
                <td>
                    <button class="btn btn-sm btn-outline-danger" onclick="eliminarInsumo(${index})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>
        `;
        tbody.innerHTML += fila;
    });
    
    document.getElementById('totalItems').textContent = `(${totalItems})`;
    document.getElementById('btnGuardar').disabled = insumosSeleccionados.length === 0;
}

function actualizarCantidad(index, cantidad) {
    insumosSeleccionados[index].cantidad = parseInt(cantidad);
    actualizarTabla();
}

function eliminarInsumo(index) {
    insumosSeleccionados.splice(index, 1);
    actualizarTabla();
}

function agregarInsumo() {
    const termino = document.getElementById('buscarInsumo').value;
    if (termino.length > 2) {
        mostrarInsumosFiltrados(termino);
    }
}

function guardarSolicitud() {
    if (insumosSeleccionados.length === 0) return;
    
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = window.location.pathname;
    form.innerHTML = insumosSeleccionados.map(i => 
        `<input type="hidden" name="insumos[]" value="${i.id}">
         <input type="hidden" name="cantidades[]" value="${i.cantidad}">`
    ).join('');
    
    document.body.appendChild(form);
    form.submit();
}
