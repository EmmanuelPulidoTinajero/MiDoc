import { CommonModule } from '@angular/common';
import { HttpClient, HttpClientModule } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

interface Doctor {
  id: string;
  name: string;
  specialty: string;
  location: string;
  price: number;
}

@Component({
  selector: 'midoc-root',
  standalone: true,
  imports: [CommonModule, FormsModule, HttpClientModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent {
  private readonly http = inject(HttpClient);
  readonly apiUrl = globalThis.location.hostname === 'localhost'
    ? 'http://localhost:3000'
    : 'https://2obhgm1da2.execute-api.us-east-1.amazonaws.com';
  doctors: Doctor[] = [];
  specialty = '';
  message = 'Busca un profesional para comenzar.';

  search(): void {
    this.http.get<{ data: Doctor[] }>(`${this.apiUrl}/api/doctors`, { params: { specialty: this.specialty } })
      .subscribe({
        next: result => { this.doctors = result.data; this.message = `${result.data.length} profesional(es) encontrado(s).`; },
        error: () => { this.message = 'No fue posible consultar la API.'; }
      });
  }

  book(doctor: Doctor): void {
    this.message = `Seleccionaste a ${doctor.name}. Inicia sesión en la API para confirmar la cita.`;
  }
}
