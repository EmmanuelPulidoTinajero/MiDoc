import { Component, inject, signal } from '@angular/core';
import { AccesoComponent } from './acceso.component';
import { ApiService } from './api.service';
import { BusquedaComponent } from './busqueda.component';
import { CitasComponent } from './citas.component';
import { ExpedienteComponent } from './expediente.component';
import { PanelDoctorComponent } from './panel-doctor.component';

type Tab = 'buscar' | 'citas' | 'expediente' | 'panel' | 'acceso';

@Component({
  selector: 'midoc-root',
  standalone: true,
  imports: [AccesoComponent, BusquedaComponent, CitasComponent, ExpedienteComponent, PanelDoctorComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent {
  readonly api = inject(ApiService);
  readonly tab = signal<Tab>(this.api.isDoctor() ? 'panel' : 'buscar');

  constructor() {
    if (this.api.user()) {
      void this.api.refreshProfile().catch(() => undefined);
    }
  }

  signedIn(): void {
    this.tab.set(this.api.isDoctor() ? 'panel' : 'buscar');
  }

  logout(): void {
    this.api.logout();
    this.tab.set('buscar');
  }
}
