import { bootstrapApplication } from '@angular/platform-browser';
import { loadConfig } from './app/api.service';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';

// Primero se lee config.json (URL de la API y modo de pago) y después arranca la app.
void loadConfig().then(() => bootstrapApplication(AppComponent, appConfig));
