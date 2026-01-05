function InsumosApp(dataId) {
    this.dataEl = document.getElementById(dataId);
    this.todosInsumos = JSON.parse(this.dataEl.dataset.insumos);
    this.pacienteId = parseInt(this.dataEl.dataset.pacienteId);
    this.seleccionados = [];
    
    this.init = function() {
        var saved = localStorage.getItem('insumos_' + this.pacienteId);
        if (saved) this.seleccionados = JSON.parse(saved);
        
        this.actualizarPrevisualizacion();
        this.bindEvents();
    };
    
    this.bindEvents = function() {
        document.getElementById('buscarInsumo').addEventListener('input', this.buscarInsumo.bind(this));
        document.getElementById('btnSolicitarTodos').addEventListener('click', this.solicitarTodos.bind(this));
    };
    
    this.buscarInsumo = function() {
        var termino = this.value.toLowerCase();
        var resultadosDiv = document.getElementById('resultadosBusqueda');
        
        if (termino.length < 2) {
            resultadosDiv.style.display = 'none';
            return;
        }
        
        var filtrados = this.todosInsumos.filter(function(i) {
            return i.nombre.toLowerCase().indexOf(termino) !== -1;
        }).slice(0, 8);
        
        document.getElementById('countResultados').textContent = '(' + filtrados.length + ')';
        document.getElementById('listaInsumos').innerHTML = this.generarHtmlResultados(filtrados);
        resultadosDiv.style.display = 'block';
    };
    
    this.generarHtmlResultados = function(filtrados) {
        var html = '';
        for (var i = 0; i < filtrados.length; i++) {
            var insumo = filtrados[i];
            var yaSeleccionado = this.buscarPorId(insumo.id);
            html += '<div class="col-md-6 mb-2">' +
                '<div class="card h-100 shadow-sm ' + (yaSeleccionado ? 'border-success' : '') + '">' +
                '<div class="card-body p-3">' +
                '<h6>' + insumo.nombre + '</h6>' +
                '<small class="text-muted">Stock: ' + insumo.stock_actual + '</small>' +
                '<div class="mt-2">';
            
            if (yaSeleccionado) {
                html += '<span class="badge bg-success">✓ Seleccionado</span>';
            } else {
                html += '<input type="number" class="form-control form-control-sm mt-1" ' +
                    'id="cant_' + insumo.id + '" value="1" min="1" max="' + insumo.stock_actual + '">' +
                    '<button class="btn btn-sm btn-success w-100 mt-1" ' +
                    'onclick="insumosApp.agregarInsumo(' + insumo.id + ')">➕ Agregar</button>';
            }
            
            html += '</div></div></div></div>';
        }
        return html;
    };
    
    this.agregarInsumo = function(id) {
        var insumo = this.buscarPorIdGlobal(id);
        var cantidadInput = document.getElementById('cant_' + id);
        var cantidad = parseInt(cantidadInput.value);
        
        if (cantidad > insumo.stock_actual) {
            alert('❌ Stock insuficiente');
            return;
        }
        
        var existe = this.buscarPorId(id);
        if (existe) {
            existe.cantidad += cantidad;
        } else {
            this.seleccionados.push({
                id: insumo.id,
                nombre: insumo.nombre,
                stock_actual: insumo.stock_actual,
                cantidad: cantidad
            });
        }
        
        localStorage.setItem('insumos_' + this.pacienteId, JSON.stringify(this.seleccionados));
        this.actualizarPrevisualizacion();
        document.getElementById('buscarInsumo').value = '';
        document.getElementById('resultadosBusqueda').style.display = 'none';
    };
    
    this.buscarPorId = function(id) {
        for (var i = 0; i < this.seleccionados.length; i++) {
            if (this.seleccionados[i].id === id) return this.seleccionados[i];
        }
        return null;
    };
    
    this.buscarPorIdGlobal = function(id) {
        for (var i = 0; i < this.todosInsumos.length; i++) {
            if (this.todosInsumos[i].id === id) return this.todosInsumos[i];
        }
        return null;
    };
    
    this.eliminarInsumo = function(id) {
        for (var i = 0; i < this.seleccionados.length; i++) {
            if (this.seleccionados[i].id === id) {
                this.seleccionados.splice(i, 1);
                break;
            }
        }
        localStorage.setItem('insumos_' + this.pacienteId, JSON.stringify(this.seleccionados));
        this.actualizarPrevisualizacion();
    };
    
    this.actualizarPrevisualizacion = function() {
        var lista = document.getElementById('listaSeleccionados');
        var html = '';
        var totalItems = 0;
        var stockOK = true;
        
        for (var i = 0; i < this.seleccionados.length; i++) {
            var insumo = this.seleccionados[i];
            totalItems++;
            var stockRestante = insumo.stock_actual - insumo.cantidad;
            if (stockRestante < 0) stockOK = false;
            
            html += '<div class="d-flex justify-content-between align-items-center mb-2 p-2 bg-light rounded">' +
                '<div><small>' + insumo.nombre + '</small><br>' +
                '<span class="badge ' + (stockRestante >= 0 ? 'bg-success' : 'bg-danger') + '">' + insumo.cantidad + '</span></div>' +
                '<button class="btn btn-sm btn-outline-danger" onclick="insumosApp.eliminarInsumo(' + insumo.id + ')">🗑️</button>' +
                '</div>';
        }
        
        lista.innerHTML = html;
        document.getElementById('totalItems').textContent = '(' + totalItems + ')';
        document.getElementById('totalSeleccionados').textContent = totalItems;
        document.getElementById('btnSolicitarTodos').classList.toggle('d-none', totalItems === 0);
        
        document.getElementById('stockWarning').innerHTML = 
            stockOK ? '' : '<i class="fas fa-exclamation-triangle text-danger"></i> Stock insuficiente';
    };
    
    this.solicitarTodos = function() {
        if (this.seleccionados.length === 0) return;
        
        var form = document.createElement('form');
        form.method = 'POST';
        form.style.display = 'none';
        
        for (var i = 0; i < this.seleccionados.length; i++) {
            var insumo = this.seleccionados[i];
            form.innerHTML += '<input type="hidden" name="insumos[]" value="' + insumo.id + '">' +
                             '<input type="hidden" name="cantidades[]" value="' + insumo.cantidad + '">';
        }
        
        document.body.appendChild(form);
        form.submit();
    };
    
    this.init();
}
