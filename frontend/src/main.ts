import { provideHttpClient } from '@angular/common/http';
import { bootstrapApplication } from '@angular/platform-browser';
import { loadConfig } from './app/api.service';
import { AppComponent } from './app/app.component';

// Primero se lee config.json (URL de la API publicada por Terraform) y después arranca la app.
loadConfig()
  .then(() => bootstrapApplication(AppComponent, { providers: [provideHttpClient()] }))
  .catch((error: unknown) => {
    console.error('No fue posible iniciar MiDoc', error);
  });
