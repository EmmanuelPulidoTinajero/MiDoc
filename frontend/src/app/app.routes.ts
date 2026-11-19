import { Routes } from '@angular/router';
import { AccesoComponent } from './acceso.component';
import { authGuard, doctorGuard, guestGuard, patientGuard } from './auth.guards';
import { BusquedaComponent } from './busqueda.component';
import { CitasComponent } from './citas.component';
import { ExpedienteComponent } from './expediente.component';
import { MensajesComponent } from './mensajes.component';
import { PanelDoctorComponent } from './panel-doctor.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'buscar' },
  { path: 'buscar', component: BusquedaComponent, title: 'Buscar profesionales · MiDoc' },
  { path: 'acceso', component: AccesoComponent, canActivate: [guestGuard], title: 'Acceso · MiDoc' },
  { path: 'citas', component: CitasComponent, canActivate: [authGuard], title: 'Citas · MiDoc' },
  {
    path: 'expediente',
    component: ExpedienteComponent,
    canActivate: [patientGuard],
    title: 'Mi expediente · MiDoc',
  },
  { path: 'mensajes', component: MensajesComponent, canActivate: [authGuard], title: 'Mensajes · MiDoc' },
  {
    path: 'panel/suscripcion',
    component: PanelDoctorComponent,
    canActivate: [doctorGuard],
    data: { section: 'suscripcion' },
    title: 'Suscripción · MiDoc',
  },
  { path: 'panel', component: PanelDoctorComponent, canActivate: [doctorGuard], title: 'Mi panel · MiDoc' },
  { path: '**', redirectTo: 'buscar' },
];
